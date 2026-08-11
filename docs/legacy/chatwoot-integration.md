# Chatwoot Integration

The Dashboard App listens for `window.message` events and normalizes account, conversation, contact, inbox, status, labels, and custom attributes.

The frontend treats this payload only as UI context. Backend validation against Chatwoot should happen in Convex actions before sensitive changes.
