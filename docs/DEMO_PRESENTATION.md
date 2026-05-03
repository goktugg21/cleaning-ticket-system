# Local Demo Presentation Flow

This document is the recommended flow for presenting the cleaning ticket system locally over HTTP.

## 1. Start the demo

Start the local HTTP demo stack:

    FRONTEND_PORT=8080 ./scripts/demo_up.sh

Open:

    http://localhost:8080

The app is intentionally running without HTTPS in local demo mode.

## 2. Explain the deployment model

Explain:

- The app runs as Docker containers.
- The browser opens the React frontend.
- Nginx serves the frontend and proxies API requests to Django.
- Django talks to PostgreSQL and Redis.
- Uploaded files are stored in a persistent Docker volume.
- In real deployment, HTTPS will be handled outside the app by firewall or Nginx Proxy Manager.
- The app itself will continue to run internally over HTTP.

Expected production request flow:

    Browser HTTPS
      -> Firewall / Nginx Proxy Manager
      -> Internal HTTP app port
      -> Docker frontend
      -> Django backend
      -> PostgreSQL / Redis / media volume

## 3. Demo users

Use these accounts:

    Super admin:    admin@example.com        / Admin12345!
    Company admin:  companyadmin@example.com / Test12345!
    Manager:        manager@example.com      / Test12345!
    Customer:       customer@example.com     / Test12345!

Use a private/incognito window when switching users.

## 4. Customer flow

Login as:

    customer@example.com / Test12345!

Show:

- Customer dashboard
- Customer can see their own tickets
- Customer can create a ticket
- Customer can upload an allowed attachment
- Customer cannot create internal/hidden notes
- Customer cannot see hidden/internal manager notes
- Customer cannot assign tickets
- Customer cannot access tickets outside their scope

Recommended action:

1. Create a new ticket.
2. Add a public reply.
3. Upload a public attachment.
4. Open the ticket detail page and show the timeline.

## 5. Manager flow

Open a new private/incognito window.

Login as:

    manager@example.com / Test12345!

Show:

- Manager can see building tickets
- Manager can change ticket status
- Manager can add internal notes
- Manager can upload hidden/internal attachments
- Manager can assign tickets to valid managers for the same building

Recommended action:

1. Open the customer-created ticket.
2. Move status from `OPEN` to `IN_PROGRESS`.
3. Add an internal note.
4. Upload a hidden attachment.
5. Move status to `WAITING_CUSTOMER_APPROVAL`.

## 6. Customer approval flow

Return to customer window.

Show:

- Customer sees the public ticket update.
- Customer does not see the internal manager note.
- Customer does not see hidden manager attachment.
- Customer can approve the ticket when it is waiting for approval.

Recommended action:

1. Refresh ticket detail.
2. Confirm hidden/internal content is not visible.
3. Approve the ticket.

## 7. Company admin flow

Open a new private/incognito window.

Login as:

    companyadmin@example.com / Test12345!

Show:

- Company admin can see company tickets.
- Company admin can close approved tickets.
- Company admin has broader access than a customer but is still scoped to their company.

Recommended action:

1. Open the approved ticket.
2. Close the ticket.

## 8. Super admin flow

Open a new private/incognito window.

Login as:

    admin@example.com / Admin12345!

Show:

- Super admin can see all companies and scopes.
- Super admin can access all tickets.
- Super admin can see internal notes and hidden attachments.

## 9. File upload checks

Explain:

Allowed file types:

- PNG
- JPG
- JPEG
- WEBP
- PDF
- HEIC
- HEIF

Rejected example:

- TXT

Limit:

- 10 MB maximum attachment size

## 10. Backup and restore readiness

Explain that the system includes:

- PostgreSQL backup script
- Media backup script
- PostgreSQL restore script
- PostgreSQL restore smoke test
- Final validation script

Useful commands:

    ./scripts/backup_postgres.sh
    ./scripts/backup_media.sh
    RESTORE_TEST_CONFIRM=YES FRONTEND_PORT=18080 ./scripts/prod_restore_test.sh

## 11. Final validation

Explain that this full validation has already passed:

    ./scripts/final_validation.sh

It includes:

- Backend check
- Migration dry-run
- API smoke tests
- Scope isolation tests
- Attachment tests
- Assignment tests
- Frontend build
- Production smoke test
- Production upload/download test
- PostgreSQL restore test

## 12. Stop demo

After the presentation:

    ./scripts/demo_down.sh
