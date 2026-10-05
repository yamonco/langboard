from langboard_shared.core.routing import BaseFormModel, form_model


@form_model
class ChangeAttachmentNameForm(BaseFormModel):
    attachment_name: str


@form_model
class ProcessAttachmentDocumentForm(BaseFormModel):
    reprocess: bool = False
