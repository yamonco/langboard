from inspect import Parameter, signature
from json import dumps as json_dumps
from types import UnionType
from typing import (
    Any,
    Callable,
    Literal,
    Sequence,
    _UnionGenericAlias,  # type: ignore
)
from pydantic import BaseModel
from pydantic_core import from_json
from ...Env import Env


class TaskParameters:
    def __init__(self, *args: Any, **kwargs: Any):
        self.__args = args
        self.__kwargs = kwargs
        self.__curernt_arg_index = 0

    def pack(self):
        new_args = []
        new_kwargs = {}
        for i in range(len(self.__args)):
            arg = self.__args[i]
            new_args.append(self.__pack_value(arg))

        for key, value in self.__kwargs.items():
            new_kwargs[key] = self.__pack_value(value)

        new_args = tuple(new_args)

        payload = json_dumps([new_args, new_kwargs], ensure_ascii=False, separators=(",", ":"), default=str).encode()
        if len(payload) > Env.BROKER_TASK_MAX_PAYLOAD_KB * 1024:
            raise ValueError(f"Broker task payload exceeds the {Env.BROKER_TASK_MAX_PAYLOAD_KB} KB limit")

        return new_args, new_kwargs

    def unpack(self, func: Callable) -> tuple[tuple, dict]:
        params = signature(func).parameters
        new_args = []
        new_kwargs = {}

        for param_name in params:
            param = params[param_name]
            if param.kind == Parameter.VAR_POSITIONAL or param.kind == Parameter.VAR_KEYWORD:
                raise Exception("Can't use *args or **kwargs in async task.")

            arg_type, value = self.__unpack(param_name, param)
            if arg_type == "arg":
                new_args.append(value)
            else:
                new_kwargs[param_name] = value

        new_args = tuple(new_args)

        return new_args, new_kwargs

    def __pack_value(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        else:
            return value

    def __unpack(self, param_name: str, parameter: Parameter) -> tuple[Literal["arg", "kwarg"], Any]:
        annotation = parameter.annotation

        arg_type, value = self.__get_param_value(param_name)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return arg_type, annotation.model_validate(from_json(value))
        elif isinstance(annotation, type) and annotation is Sequence:
            return arg_type, list(value)
        elif isinstance(annotation, UnionType) or isinstance(annotation, _UnionGenericAlias):
            for sub_annotation in annotation.__args__:  # type: ignore
                try:
                    if isinstance(sub_annotation, type) and issubclass(sub_annotation, BaseModel):
                        return arg_type, sub_annotation.model_validate(from_json(value))
                    elif sub_annotation is Sequence:
                        return arg_type, list(value)
                except Exception:
                    continue

            return arg_type, value
        else:
            return arg_type, value

    def __get_param_value(self, param_name: str) -> tuple[Literal["arg", "kwarg"], Any]:
        if param_name in self.__kwargs:
            arg_type = "kwarg"
            value = self.__kwargs[param_name]
        else:
            arg_type = "arg"
            value = self.__args[self.__curernt_arg_index]
            self.__curernt_arg_index += 1
        return arg_type, value
