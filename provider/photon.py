from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from provider.client import PhotonClient, PhotonError


class PhotonProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            PhotonClient(credentials).call("list_spaces", query={"pageSize": 1})
        except PhotonError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from None
