from asyncio import run as run_async
from json import dumps as json_dumps
from json import loads as json_loads
from os.path import dirname
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Concatenate, Coroutine, Generic, ParamSpec, Protocol, TypeVar, cast, overload
from celery import Celery
from celery.app.task import Task
from celery.apps import worker
from celery.apps.worker import Worker
from celery.signals import celeryd_after_setup, setup_logging, worker_process_init
from ...Env import Env
from ...ModuleLoader import ModuleLoader
from ..logger import Logger
from ..utils.decorators import class_instance
from .TaskParameters import TaskParameters


_TParams = ParamSpec("_TParams")
_TReturn = TypeVar("_TReturn", covariant=True)


class _Task(Protocol, Generic[_TParams, _TReturn]):
    def __call__(self, *args: _TParams.args, **kwargs: _TParams.kwargs) -> _TReturn: ...  # type: ignore


logger = Logger.use("broker")


@setup_logging.connect
def _(*args, **kwargs):
    logger.handlers.clear()
    logger.handlers.extend(Logger.get_handlers())
    return logger


@celeryd_after_setup.connect
def _(sender: str, instance: Worker, **kwargs) -> None:
    instance.emit_banner = lambda: None


worker.safe_say = lambda _, __: None


@class_instance()
class Broker:
    _schemas: dict[str, dict[str, Any]] = {}

    def __init__(self):
        if Env.CACHE_TYPE == "in-memory":
            self.broker_url = "memory://"
            self.api_url = "cache+memory://"
        else:
            self.broker_url = Env.CACHE_URL
            self.api_url = Env.CACHE_URL

        self.celery = Celery(Env.PROJECT_NAME)

        self.celery.conf.update(
            broker_url=self.broker_url,
            result_api=self.api_url,
            task_track_started=True,
            timezone="UTC",
        )

        self.logger = logger

    def is_in_memory(self) -> bool:
        return Env.CACHE_TYPE == "in-memory"

    def on_worker_process_init(self, func: Callable) -> Callable:
        worker_process_init.connect(func)
        return func

    @overload
    def wrap_async_task_decorator(
        self, param: Callable[Concatenate[_TParams], Coroutine[Any, Any, Any]]
    ) -> _Task[_TParams, Any]: ...
    @overload
    def wrap_async_task_decorator(
        self, param: dict
    ) -> Callable[[Callable[Concatenate[_TParams], Coroutine[Any, Any, Any]]], _Task[_TParams, Any]]: ...
    def wrap_async_task_decorator(
        self, param: Callable[Concatenate[_TParams], Coroutine[Any, Any, Any]] | dict
    ) -> (
        _Task[_TParams, Any]
        | Callable[[Callable[Concatenate[_TParams], Coroutine[Any, Any, Any]]], _Task[_TParams, Any]]
    ):
        """Wrap async celery task decorator.

        You don't need to use `@Broker.celery.task` decorator.

        DO NOT use *args or **kwargs in async task.
        """

        kwargs = {}
        if isinstance(param, dict):
            kwargs = param

        def wrapped_task(func: Callable[Concatenate[_TParams], Coroutine[Any, Any, Any]]):
            if Env.CACHE_TYPE == "in-memory":

                def local_task(*args: _TParams.args, **kwargs: _TParams.kwargs):
                    return Thread(target=run_async, args=(func(*args, **kwargs),)).start()

                return local_task

            def task(*args: _TParams.args, **kwargs: _TParams.kwargs) -> Any:
                new_args, new_kwargs = self.__unpack_task_parameters(func, *args, **kwargs)
                return run_async(func(*new_args, **new_kwargs))

            task.__module__ = func.__module__
            task.__name__ = func.__name__

            return self.__create_async_task(cast(Any, self.celery.task(**kwargs)(task)))

        if isinstance(param, dict):
            return wrapped_task
        else:
            return wrapped_task(param)

    @overload
    def wrap_sync_task_decorator(self, param: Callable[Concatenate[_TParams], Any]) -> _Task[_TParams, Any]: ...
    @overload
    def wrap_sync_task_decorator(
        self, param: dict
    ) -> Callable[[Callable[Concatenate[_TParams], Any]], _Task[_TParams, Any]]: ...
    def wrap_sync_task_decorator(
        self, param: Callable[Concatenate[_TParams], Any] | dict
    ) -> _Task[_TParams, Any] | Callable[[Callable[Concatenate[_TParams], Any]], _Task[_TParams, Any]]:
        """Wrap sync celery task decorator.

        You don't need to use `@Broker.celery.task` decorator.

        DO NOT use *args or **kwargs in sync task.
        """

        kwargs = {}
        if isinstance(param, dict):
            kwargs = param

        def wrapped_task(func: Callable[Concatenate[_TParams], Any]):
            if Env.CACHE_TYPE == "in-memory":

                def local_task(*args: _TParams.args, **kwargs: _TParams.kwargs):
                    return func(*args, **kwargs)

                return local_task

            def task(*args: _TParams.args, **kwargs: _TParams.kwargs) -> Any:
                new_args, new_kwargs = self.__unpack_task_parameters(func, *args, **kwargs)
                return func(*new_args, **new_kwargs)

            task.__module__ = func.__module__
            task.__name__ = func.__name__

            return self.__create_sync_task(cast(Any, self.celery.task(**kwargs)(task)))

        if isinstance(param, dict):
            return wrapped_task
        else:
            return wrapped_task(param)

    def start(self, argv: list[str] | None = None):
        module_loader = ModuleLoader(Path(dirname(__file__)).parent.parent, cast(str, __package__))
        module_loader.load("tasks", "Task")
        if argv is None:
            argv = ["worker", "--loglevel=info", "--pool=solo"]
        self._schemas.clear()

        try:
            if self.is_in_memory():
                self.logger.info("Broker started with in-memory cache.")
            else:
                self.logger.info("Broker started with cache: %s", Env.CACHE_URL)
            self.celery.worker_main(argv)
        except Exception:
            self.celery.close()

    def schema(self, group: str, schema: dict):
        schema_file = Env.SCHEMA_DIR / f"{group}.json"
        if group not in self._schemas:
            if schema_file.exists():
                try:
                    schema_json = json_loads(schema_file.read_text())
                except Exception:
                    schema_json = {}
            else:
                schema_json = {}
            self._schemas[group] = schema_json
        else:
            schema_json = self._schemas[group]

        with open(schema_file, "w") as f:
            schema_json.update(schema)
            f.write(json_dumps(schema_json))

        def decorator(func):
            return func

        return decorator

    def get_schema(self, group: str) -> dict[str, Any]:
        schema_file = Env.SCHEMA_DIR / f"{group}.json"
        if schema_file.exists():
            return json_loads(schema_file.read_text())
        else:
            return {}

    def __create_async_task(self, func: Callable[Concatenate[_TParams], Any]) -> _Task[_TParams, Any]:
        def inner(*args: _TParams.args, **kwargs: _TParams.kwargs) -> Any:
            new_args, new_kwargs = self.__pack_task_parameters(*args, **kwargs)
            return cast(Task, func).apply_async(args=new_args, kwargs=new_kwargs)

        return inner

    def __create_sync_task(self, func: Callable[Concatenate[_TParams], Any]) -> _Task[_TParams, Any]:
        def inner(*args: _TParams.args, **kwargs: _TParams.kwargs) -> Any:
            new_args, new_kwargs = self.__pack_task_parameters(*args, **kwargs)
            return cast(Task, func).apply(args=new_args, kwargs=new_kwargs)

        return inner

    def __pack_task_parameters(self, *args: Any, **kwargs: Any):
        task_parameters = TaskParameters(*args, **kwargs)
        return task_parameters.pack()

    def __unpack_task_parameters(self, func: Callable, *args: Any, **kwargs: Any):
        task_parameters = TaskParameters(*args, **kwargs)
        return task_parameters.unpack(func)
