# Spec Delta

## REMOVED Requirements

### Requirement: The chat page asks for the token when seeding is refused
**Reason**: The knowledge base editor moves from the customer chat page to the admin page, which asks for the token when it opens and again when a save is refused. See the `admin-page` capability.
**Migration**: Edit and save documents at `/admin` instead of `/chat`. `/seed`, its bearer token and the CLI chatbot are unchanged.
