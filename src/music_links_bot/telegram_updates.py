"""Update types shared by polling, webhooks and PTB compatibility handlers."""

ALLOWED_UPDATES = (
    "message",
    "channel_post",
    "callback_query",
    "inline_query",
    "chosen_inline_result",
    "guest_message",
    "stopped_message_generation",
)


def native_field(value, name):
    field = getattr(value, name, None)
    if field is not None:
        return field
    return (getattr(value, "api_kwargs", None) or {}).get(name)
