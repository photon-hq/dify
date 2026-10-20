from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from provider.client import PhotonClient, PhotonError, page_items


class PhotonProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            client = PhotonClient(credentials)
            page_items(client.request("GET", "/spaces", params={"pageSize": 1}))
        except PhotonError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from None
