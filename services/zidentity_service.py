"""ZIdentity business logic layer.

Wraps ZIdentityClient with audit logging for every mutating operation.
"""

from typing import Dict, List, Optional

from lib.zidentity_client import ZIdentityClient
from services import audit_service


class ZIdentityService:
    def __init__(self, client: ZIdentityClient, tenant_id: Optional[int] = None):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(
        self,
        login_name: Optional[str] = None,
        display_name: Optional[str] = None,
        primary_email: Optional[str] = None,
        domain_name: Optional[str] = None,
    ) -> List[Dict]:
        result = self.client.list_users(
            login_name=login_name,
            display_name=display_name,
            primary_email=primary_email,
            domain_name=domain_name,
        )
        audit_service.log(
            product="ZIdentity",
            operation="list_users",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            details={"count": len(result)},
        )
        return result

    def get_user(self, user_id: str) -> Dict:
        return self.client.get_user(user_id)

    def list_user_groups(self, user_id: str) -> List[Dict]:
        return self.client.list_user_groups(user_id)

    def get_admin_entitlement(self, user_id: str) -> Dict:
        return self.client.get_admin_entitlement(user_id)

    def get_service_entitlement(self, user_id: str) -> Dict:
        return self.client.get_service_entitlement(user_id)

    def reset_password(self, user_id: str, username: str) -> Dict:
        result = self.client.reset_password(user_id)
        audit_service.log(
            product="ZIdentity",
            operation="reset_password",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=user_id,
            resource_name=username,
        )
        return result

    def update_password(
        self,
        user_id: str,
        username: str,
        password: str,
        reset_on_login: bool = False,
    ) -> Dict:
        result = self.client.update_password(user_id, password, reset_on_login)
        audit_service.log(
            product="ZIdentity",
            operation="update_password",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=user_id,
            resource_name=username,
        )
        return result

    def skip_mfa(self, user_id: str, username: str, until_timestamp: int) -> Dict:
        result = self.client.skip_mfa(user_id, until_timestamp)
        audit_service.log(
            product="ZIdentity",
            operation="skip_mfa",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=user_id,
            resource_name=username,
            details={"until_timestamp": until_timestamp},
        )
        return result

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def list_groups(
        self,
        name: Optional[str] = None,
        exclude_dynamic: bool = False,
    ) -> List[Dict]:
        result = self.client.list_groups(name=name, exclude_dynamic=exclude_dynamic)
        audit_service.log(
            product="ZIdentity",
            operation="list_groups",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="group",
            details={"count": len(result)},
        )
        return result

    def get_group(self, group_id: str) -> Dict:
        return self.client.get_group(group_id)

    def list_group_members(self, group_id: str) -> List[Dict]:
        return self.client.list_group_members(group_id)

    def add_user_to_group(
        self, group_id: str, group_name: str, user_id: str, username: str
    ) -> Dict:
        result = self.client.add_user_to_group(group_id, user_id)
        audit_service.log(
            product="ZIdentity",
            operation="add_user_to_group",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="group",
            resource_id=group_id,
            resource_name=group_name,
            details={"user_id": user_id, "username": username},
        )
        return result

    def remove_user_from_group(
        self, group_id: str, group_name: str, user_id: str, username: str
    ) -> Dict:
        result = self.client.remove_user_from_group(group_id, user_id)
        audit_service.log(
            product="ZIdentity",
            operation="remove_user_from_group",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="group",
            resource_id=group_id,
            resource_name=group_name,
            details={"user_id": user_id, "username": username},
        )
        return result

    # ------------------------------------------------------------------
    # API Clients
    # ------------------------------------------------------------------

    def list_api_clients(self, name: Optional[str] = None) -> List[Dict]:
        result = self.client.list_api_clients(name=name)
        audit_service.log(
            product="ZIdentity",
            operation="list_api_clients",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="api_client",
            details={"count": len(result)},
        )
        return result

    def get_api_client(self, client_id: str) -> Dict:
        return self.client.get_api_client(client_id)

    def get_api_client_secrets(self, client_id: str) -> Dict:
        return self.client.get_api_client_secrets(client_id)

    def add_api_client_secret(
        self, client_id: str, client_name: str, expires_at: Optional[str] = None
    ) -> Dict:
        result = self.client.add_api_client_secret(client_id, expires_at)
        audit_service.log(
            product="ZIdentity",
            operation="add_api_client_secret",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="api_client",
            resource_id=client_id,
            resource_name=client_name,
            details={"expires_at": expires_at},
        )
        return result

    def delete_api_client_secret(
        self, client_id: str, client_name: str, secret_id: str
    ) -> bool:
        result = self.client.delete_api_client_secret(client_id, secret_id)
        audit_service.log(
            product="ZIdentity",
            operation="delete_api_client_secret",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="api_client",
            resource_id=client_id,
            resource_name=client_name,
            details={"secret_id": secret_id},
        )
        return result

    def delete_api_client(self, client_id: str, client_name: str) -> bool:
        result = self.client.delete_api_client(client_id)
        audit_service.log(
            product="ZIdentity",
            operation="delete_api_client",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="api_client",
            resource_id=client_id,
            resource_name=client_name,
        )
        return result
