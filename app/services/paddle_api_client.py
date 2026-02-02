"""Paddle API client for direct subscription management operations."""

import httpx
from typing import Optional, Dict, Any, List
import structlog

from app.config import settings

logger = structlog.get_logger()


class PaddleAPIError(Exception):
    """Exception raised when Paddle API returns an error."""
    
    def __init__(self, status_code: int, error_code: str, message: str, detail: Optional[Dict] = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"Paddle API Error [{error_code}]: {message}")


class PaddleAPIClient:
    """HTTP client for Paddle API operations."""
    
    def __init__(self):
        self.base_url = settings.paddle_api_url.rstrip("/")
        self.api_key = settings.paddle_api_key
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Paddle API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Handle Paddle API response and raise appropriate errors."""
        try:
            data = response.json()
        except Exception:
            data = {"error": {"type": "unknown", "detail": response.text}}
        
        if response.status_code >= 400:
            error = data.get("error", {})
            raise PaddleAPIError(
                status_code=response.status_code,
                error_code=error.get("type", "unknown_error"),
                message=error.get("detail", "Unknown error occurred"),
                detail=error
            )
        
        return data
    
    async def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """
        Get subscription details from Paddle.
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            
        Returns:
            Subscription data from Paddle
        """
        logger.info("Getting subscription from Paddle", subscription_id=subscription_id)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/subscriptions/{subscription_id}",
                headers=self._get_headers(),
                timeout=30.0
            )
            
        result = self._handle_response(response)
        logger.info("Got subscription from Paddle", subscription_id=subscription_id)
        return result.get("data", {})
    
    async def cancel_subscription(
        self,
        subscription_id: str,
        effective_from: str = "next_billing_period"
    ) -> Dict[str, Any]:
        """
        Cancel a subscription.
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            effective_from: When cancellation takes effect:
                - "next_billing_period": Cancel at end of current period (default)
                - "immediately": Cancel immediately
                
        Returns:
            Updated subscription data from Paddle
        """
        logger.info(
            "Cancelling subscription via Paddle API",
            subscription_id=subscription_id,
            effective_from=effective_from
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/subscriptions/{subscription_id}/cancel",
                headers=self._get_headers(),
                json={"effective_from": effective_from},
                timeout=30.0
            )
        
        result = self._handle_response(response)
        logger.info(
            "Successfully cancelled subscription via Paddle",
            subscription_id=subscription_id,
            effective_from=effective_from
        )
        return result.get("data", {})
    
    async def update_subscription(
        self,
        subscription_id: str,
        items: Optional[List[Dict[str, Any]]] = None,
        proration_billing_mode: str = "prorated_immediately",
        next_billed_at: Optional[str] = None,
        discount_id: Optional[str] = None,
        custom_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Update a subscription (upgrade/downgrade).
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            items: List of subscription items with price_id and quantity
                   Example: [{"price_id": "pri_xxx", "quantity": 1}]
            proration_billing_mode: How to handle proration:
                - "prorated_immediately": Bill prorated amount immediately
                - "prorated_next_billing_period": Bill at next period
                - "full_immediately": Bill full amount immediately
                - "full_next_billing_period": Bill full amount at next period
                - "do_not_bill": Don't bill for the change
            next_billed_at: Optional RFC 3339 datetime for next billing
            discount_id: Optional discount ID to apply
            custom_data: Optional custom data to attach
            
        Returns:
            Updated subscription data from Paddle
        """
        logger.info(
            "Updating subscription via Paddle API",
            subscription_id=subscription_id,
            items=items,
            proration_billing_mode=proration_billing_mode
        )
        
        payload: Dict[str, Any] = {}
        
        if items is not None:
            payload["items"] = items
            payload["proration_billing_mode"] = proration_billing_mode
            
        if next_billed_at:
            payload["next_billed_at"] = next_billed_at
            
        if discount_id:
            payload["discount"] = {
                "id": discount_id,
                "effective_from": "immediately"
            }
            
        if custom_data:
            payload["custom_data"] = custom_data
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/subscriptions/{subscription_id}",
                headers=self._get_headers(),
                json=payload,
                timeout=30.0
            )
        
        result = self._handle_response(response)
        logger.info(
            "Successfully updated subscription via Paddle",
            subscription_id=subscription_id
        )
        return result.get("data", {})
    
    async def pause_subscription(
        self,
        subscription_id: str,
        effective_from: str = "next_billing_period",
        resume_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pause a subscription.
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            effective_from: When pause takes effect:
                - "next_billing_period": Pause at end of current period (default)
                - "immediately": Pause immediately
            resume_at: Optional RFC 3339 datetime to automatically resume
            
        Returns:
            Updated subscription data from Paddle
        """
        logger.info(
            "Pausing subscription via Paddle API",
            subscription_id=subscription_id,
            effective_from=effective_from,
            resume_at=resume_at
        )
        
        payload: Dict[str, Any] = {"effective_from": effective_from}
        if resume_at:
            payload["resume_at"] = resume_at
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/subscriptions/{subscription_id}/pause",
                headers=self._get_headers(),
                json=payload,
                timeout=30.0
            )
        
        result = self._handle_response(response)
        logger.info(
            "Successfully paused subscription via Paddle",
            subscription_id=subscription_id
        )
        return result.get("data", {})
    
    async def resume_subscription(
        self,
        subscription_id: str,
        effective_from: str = "immediately"
    ) -> Dict[str, Any]:
        """
        Resume a paused subscription.
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            effective_from: When resume takes effect:
                - "immediately": Resume immediately (default)
                - "next_billing_period": Resume at next period
                
        Returns:
            Updated subscription data from Paddle
        """
        logger.info(
            "Resuming subscription via Paddle API",
            subscription_id=subscription_id,
            effective_from=effective_from
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/subscriptions/{subscription_id}/resume",
                headers=self._get_headers(),
                json={"effective_from": effective_from},
                timeout=30.0
            )
        
        result = self._handle_response(response)
        logger.info(
            "Successfully resumed subscription via Paddle",
            subscription_id=subscription_id
        )
        return result.get("data", {})
    
    async def preview_subscription_update(
        self,
        subscription_id: str,
        items: List[Dict[str, Any]],
        proration_billing_mode: str = "prorated_immediately"
    ) -> Dict[str, Any]:
        """
        Preview a subscription update without applying changes.
        
        Args:
            subscription_id: Paddle subscription ID (sub_xxx)
            items: List of subscription items with price_id and quantity
            proration_billing_mode: How proration would be handled
            
        Returns:
            Preview data including immediate_transaction, update_summary
        """
        logger.info(
            "Previewing subscription update via Paddle API",
            subscription_id=subscription_id,
            items=items
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/subscriptions/{subscription_id}/preview",
                headers=self._get_headers(),
                json={
                    "items": items,
                    "proration_billing_mode": proration_billing_mode
                },
                timeout=30.0
            )
        
        result = self._handle_response(response)
        logger.info(
            "Got subscription update preview from Paddle",
            subscription_id=subscription_id
        )
        return result.get("data", {})


# Global client instance
paddle_api_client = PaddleAPIClient()
