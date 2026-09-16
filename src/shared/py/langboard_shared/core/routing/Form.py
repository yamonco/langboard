from abc import ABC
from inspect import Parameter, signature
from typing import TypeVar
from fastapi import Depends, Form
from fastapi.params import Depends as DependsType
from pydantic import BaseModel


_TFormModel = TypeVar("_TFormModel", bound="BaseFormModel")


class BaseFormModel(ABC, BaseModel):
    """Base class for all form models in the application inherited from :class:`BaseModel`.

    E.g.::

        @form_model
        class UserForm(BaseFormModel):
            email: str
            password: str

        @AppRouter.api.post("/users")
        async def create(user: UserForm = UserForm.scope()):
            ...

        @AppRouter.api.post("/users")
        async def create(user: Annotated[UserForm, UserForm.scope()]):
            ...
    """

    @staticmethod
    def from_form() -> "BaseFormModel":
        raise NotImplementedError("Must decorate the model class with the `form_model` decorator.")

    @staticmethod
    def scope():
        raise NotImplementedError("Must decorate the model class with the `form_model` decorator.")


def form_model(cls: type[_TFormModel]) -> type[_TFormModel]:
    """Decorates to convert a Pydantic model to a FastAPI form."""
    new_parameters = []

    for field_name in cls.model_fields:
        field = cls.model_fields[field_name]
        new_parameters.append(
            Parameter(
                field.alias if field.alias else field_name,
                Parameter.POSITIONAL_ONLY,
                default=Form(...) if field.is_required() else Form(field.default),
                annotation=field.annotation,
            )
        )

    def from_form(**data) -> _TFormModel:
        return cls(**data)

    def scope() -> DependsType:
        return Depends(from_form)

    sig = signature(from_form)
    sig = sig.replace(parameters=new_parameters)
    from_form.__signature__ = sig
    setattr(cls, "from_form", from_form)
    setattr(cls, "scope", scope)
    return cls
