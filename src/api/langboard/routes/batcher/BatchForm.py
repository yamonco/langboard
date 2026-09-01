from langboard_shared.core.routing import BaseFormModel, form_model
from pydantic import BaseModel, Field


class BatchFormRequestSchema(BaseModel):
    path_or_api_name: str = Field(
        ...,
        title="API Path or Name",
        description="The API path or name to be used in the request. If the API name is provided, it will be resolved to the actual path.",
    )
    method: str = Field(
        ...,
        title="HTTP Method",
        description="The HTTP method to be used for the API path.",
    )
    query: dict | None = Field(default=None)
    form: dict | None = Field(default=None)


@form_model
class BatchForm(BaseFormModel):
    request_schemas: list[BatchFormRequestSchema] = Field(
        ...,
        max_length=50,
        title="Request Schemas",
        description="""The schema of the request to be processed in the batch.
    - Example: [
        {
            "path": "<api path> or <api name>",
            "method": "Enum[GET, POST, PUT, DELETE]",
            "query?": {"field": "value"},
            "form?": {"field": "value"}
        }
    ]""",
    )
