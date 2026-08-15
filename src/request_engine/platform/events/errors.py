class ProviderEventDedupeConflict(RuntimeError):
    def __init__(self, provider_key: str, connection_key: str, provider_event_id: str) -> None:
        super().__init__(
            "provider event identity was reused with a different payload: "
            f"{provider_key}/{connection_key}/{provider_event_id}"
        )
