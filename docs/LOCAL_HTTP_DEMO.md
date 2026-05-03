# Local HTTP Demo

## Purpose

This demo mode is for showing the system locally or on a VPS without configuring SSL inside the application.

The app runs over plain HTTP on a local port, for example:

    http://localhost:8080

or on a server:

    http://SERVER_IP:8080

External HTTPS, SSL certificates, firewall routing, and Nginx Proxy Manager can be handled outside this app.

## Architecture

Expected deployment/demo architecture:

    Browser
      -> HTTPS handled by firewall / Nginx Proxy Manager / external reverse proxy
      -> HTTP to this Docker Compose app
      -> frontend container
      -> backend container
      -> PostgreSQL / Redis / media volume

The application containers do not need their own SSL certificates.

## Start demo

Run:

    FRONTEND_PORT=8080 ./scripts/demo_up.sh

Then open:

    http://localhost:8080

## Demo users

    Super admin:    admin@example.com        / Admin12345!
    Company admin:  companyadmin@example.com / Test12345!
    Manager:        manager@example.com      / Test12345!
    Customer:       customer@example.com     / Test12345!

These users are for demo/testing only.

## Stop demo

Run:

    ./scripts/demo_down.sh

To stop and also delete demo volumes:

    DEMO_DELETE_VOLUMES=YES ./scripts/demo_down.sh

## HTTPS note

For localhost demo, keep HTTPS flags disabled.

When the real system is behind external SSL termination, only enable Django HTTPS-related settings after confirming the proxy/firewall forwards the correct headers, especially:

    X-Forwarded-Proto: https

Do not enable `DJANGO_SECURE_SSL_REDIRECT=True` until the proxy forwarding behavior is confirmed, otherwise redirect loops may happen.


## Manager close and reopen behavior

During the demo, the expected status flow is:

1. Customer creates a ticket.
2. Building manager moves the ticket through the work process.
3. Building manager cannot close the ticket before customer approval.
4. Customer approves the ticket.
5. Building manager can close the ticket after customer approval.
6. Building manager can reopen a closed ticket if additional work is needed.

This is the intended workflow for the current release.
