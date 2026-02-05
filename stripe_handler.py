# backend/stripe_handler.py
import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "price_1SxW85J3ZSvE72b5DBpNyf3t")

def create_checkout_session(success_url: str, cancel_url: str, client_reference_id: str = None):
    """
    Create a Stripe checkout session for monthly subscription.
    
    Args:
        success_url: URL to redirect after successful payment
        cancel_url: URL to redirect if user cancels
        client_reference_id: User identifier (IP address or user ID)
    
    Returns:
        Dictionary with checkout session URL
    """
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=client_reference_id,  # Track which user paid
        )
        
        return {
            "success": True,
            "checkout_url": session.url,
            "session_id": session.id
        }
    
    except Exception as e:
        print(f"✗ Stripe checkout error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    """
    Verify and parse Stripe webhook event.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        return {"success": True, "event": event}
    except Exception as e:
        print(f"✗ Webhook verification failed: {e}")
        return {"success": False, "error": str(e)}