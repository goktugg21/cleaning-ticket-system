# Cleaning Ticket System — Business Logic, Roles, Permissions, and Workflows

This document explains how the system is supposed to work in plain English.

It is intentionally written as product logic, not as code logic. Developers and AI tools should read this before changing the backend or frontend. If the current code behaves differently from this document, the developer should stop, report the mismatch, and propose a safe fix instead of guessing.

---

## 1. The basic idea of the system

This system is for a cleaning/service provider company that serves multiple customer companies.

The provider company manages buildings, cleaning work, tickets, extra work requests, customer contacts, customer users, pricing, proposals, and operational assignments.

Customer companies use the system to report issues, request extra work, approve work when approval is needed, and see the work related to their own company and their own buildings.

The most important rule is simple:

A user should only see and do things that make sense for their role, their company, their assigned buildings, and their explicit permissions.

---

## 2. Provider company vs customer company

There are two different company concepts.

### Provider company

The provider company is the cleaning/service company.

In the current business situation, there is basically one provider company. Because of this, provider-side permission rules can stay simple for now.

Provider-side people are:

- Super Admin
- Provider Company Admin
- Building Manager
- Staff / Field Worker

The provider company owns the service operation. It manages buildings, customers, pricing, extra work, staff assignments, provider-side notes, and provider-side approvals.

### Customer company

A customer company is a client of the provider company.

Each customer company can have its own buildings, users, contacts, contract prices, and special rules.

Customer-side people are:

- Customer Company Admin
- Customer Location Manager
- Customer User

Each customer company may have a different contract with the provider company. This is very important for Extra Work pricing.

For example:

Customer A may have contract pricing for window cleaning but not for grass cutting.

Customer B may have contract pricing for grass cutting but not for window cleaning.

So Extra Work must not work the same way for every customer. It depends on that customer company's contract prices.

---

## 3. Core objects in the system

### Building

A building is a location where work happens.

A building can be linked to one or more customer companies.

A user should not see a building unless their role, company, or assigned permissions allow it.

### Room / area

A room or area is a smaller location inside a building. Tickets and work can be tied to rooms/areas when needed.

### Ticket

A ticket is normal operational work.

Examples:

- Something is dirty.
- Something is broken.
- A customer reports an issue.
- A provider employee creates a task.
- A staff member is assigned to do work.

A ticket may need customer approval at some points, depending on the workflow.

### Extra Work

Extra Work is work outside the normal cleaning routine.

Examples:

- Window cleaning
- Deep cleaning
- Grass cutting
- Special event cleaning
- One-time cleaning request
- Any work that may have a separate price or contract rule

Extra Work can follow two different paths:

1. Contract-priced Extra Work
2. Non-contract Extra Work that needs a proposal

This is explained in detail later.

### Service

A service is an item the provider can perform.

Examples:

- Window cleaning per square meter
- Grass cutting per square meter
- Floor polishing per hour
- Deep cleaning per room

Services are the general catalog.

### Customer-specific contract price

A customer-specific contract price says:

For this customer company, this service has this agreed price.

Example:

For Customer A:
- Window cleaning = EUR 5 per square meter

For Customer B:
- Grass cutting = EUR 2 per square meter

This is not the same as the general service catalog. The same service can have different prices for different customers.

### Proposal

A proposal is a price offer prepared by the provider when the requested Extra Work is not already covered by the customer's contract pricing.

A proposal is sent to the customer for approval or rejection.

A proposal can have multiple line items.

A proposal has customer-visible information and provider-only information.

Provider-only internal notes must never be visible to customers or staff when the note is financial/management-only.

---

## 4. Role hierarchy

## 4.1 Super Admin

The Super Admin is the highest-level system user.

Super Admin can:

- See all provider data
- See all customer companies
- See all buildings
- See all tickets
- See all extra work
- Manage provider admins
- Manage customer users
- Manage building managers
- Manage staff
- Manage permissions
- Manage global settings
- Override decisions when the system allows it
- See provider-only information
- Configure whether Provider Admins can manage customer-specific permissions

Super Admin should be able to fix or configure anything in the system.

Super Admin actions that change customer decisions or financial outcomes should still be logged clearly.

---

## 4.2 Provider Company Admin

Provider Company Admin is the main admin role for the provider company.

Because there is currently only one provider company, this role can be treated as the main operational admin role.

By default, Provider Company Admin can:

- Manage customer companies
- Manage buildings
- Manage customer-building links
- Manage customer contacts
- Manage customer users, except where restricted
- Manage staff and building managers
- Manage customer-specific pricing
- Manage services
- Create and manage tickets
- Create and manage Extra Work
- Prepare proposals
- Send proposals to customers
- Override customer approval/rejection when allowed
- Manage customer-specific permissions by default
- See provider-only notes and financial/provider-side information

Super Admin can limit or configure what Provider Company Admin is allowed to manage.

Provider Company Admin should not silently act as the customer. If they approve or reject something on behalf of a customer, the system must make that clear and store who did it and why.

---

## 4.3 Building Manager

A Building Manager is a provider-side operational manager assigned to one or more buildings.

A Building Manager should only see buildings they are assigned to, unless they have extra permission.

Default Building Manager behavior:

- Can see assigned buildings
- Can see tickets in assigned buildings
- Can manage operational status for work in assigned buildings
- Can create or manage Extra Work for assigned buildings
- Can prepare proposals for assigned buildings by default
- Can approve or reject on behalf of a customer by default, if the business process allows it
- Can see provider-side operational notes for assigned buildings
- Can see staff instructions related to assigned work

Important correction:

By default, a Building Manager may be allowed to approve or reject on behalf of a customer when the customer gave approval outside the system, for example by phone. This must not be silent.

When a Building Manager approves or rejects on behalf of a customer:

- The UI must show a clear warning.
- The user must confirm intentionally, ideally with a second confirmation.
- The system must store that the decision was made by the Building Manager on behalf of the customer.
- The system should store a reason or note.
- The audit/history must make it clear this was not the customer clicking approve themselves.

Permissions can remove this ability from a Building Manager.

A Building Manager should not:

- See buildings they are not assigned to.
- Manage customer user permissions by default.
- Change provider-company-wide settings.
- See provider-level financial/internal notes unless explicitly allowed.
- See customer-company areas outside assigned building scope.

---

## 4.4 Staff / Field Worker

Staff are the people who do the actual work.

Staff should have a clean operational view. They should not see management or pricing details.

Staff should see Extra Work only after it has become an actual assigned job/ticket/task.

Correct Staff rule:

Staff sees the operational part after Extra Work is approved and assigned to them as work.

Staff should not see:

- Proposal drafts
- Proposal prices
- Customer approval/rejection controls
- Provider financial notes
- Internal margin/cost notes
- Customer contract price management
- Permission management
- Customer company management
- Provider admin settings

Staff can see:

- Assigned work
- Building/location where they need to work
- Work description
- Operational instructions
- Staff-visible notes
- Attachments needed for the job
- Status actions needed for their assignment, such as start, complete, report issue, or add operational update

Staff should not approve customer decisions.

Staff should not prepare price proposals.

Staff should not see internal notes like "our cost is EUR X" or "margin is low".

But staff may need notes like:

- "The windows are very dirty; bring stronger material."
- "Use ladder."
- "Customer asked to avoid entrance B."
- "Bring extra cloths."

So the system needs different note visibility levels.

---

## 4.5 Customer Company Admin

Customer Company Admin is the highest customer-side user for one customer company.

Customer Company Admin can usually:

- See their own customer company
- See buildings linked to their customer company, depending on permissions
- See tickets for their customer company
- Create tickets
- Request Extra Work
- Approve or reject proposals for their company
- See customer-visible prices and proposal details
- See customer-visible comments and attachments
- Manage some customer-side users if allowed by provider permissions

Customer Company Admin should not:

- Create another Customer Company Admin by default
- Manage provider-side users
- See other customer companies
- See provider-only notes
- See staff-only internal operational notes unless those are made customer-visible
- See provider financial/cost/margin notes
- Change provider settings
- Manage provider permissions

Important correction:

Customer Company Admin should not be able to create another Customer Company Admin by default.

If the business wants customer admins to manage lower-level users, that can be allowed, but creating another top-level customer admin should remain controlled by Provider Admin or Super Admin.

---

## 4.6 Customer Location Manager

Customer Location Manager is a customer-side manager for one or more buildings.

A Customer Location Manager can be assigned to multiple buildings if allowed by Customer Company Admin, Provider Admin, or Super Admin.

A Customer Location Manager can usually:

- See assigned buildings
- See tickets for assigned buildings
- Create tickets for assigned buildings
- Request Extra Work for assigned buildings
- Approve or reject work/proposals for assigned buildings if permission allows
- See customer-visible comments, prices, and proposal information for assigned buildings

A Customer Location Manager should not:

- See buildings they are not assigned to
- See provider-only notes
- See provider financial/cost/margin notes
- Manage provider users
- Manage provider settings
- Create Customer Company Admin users
- Manage permissions unless explicitly allowed

---

## 4.7 Customer User

Customer User is a basic customer-side user.

A Customer User can usually:

- See only their allowed customer/building scope
- Create tickets if permission allows
- Request Extra Work if permission allows
- Comment on tickets if permission allows
- View customer-visible information

A Customer User may or may not approve/reject depending on permissions.

A Customer User should not:

- See provider-only notes
- See staff-only notes
- See other customers
- Manage users
- Manage permissions
- See provider internal pricing/costs

---

## 5. Permission model

The permission system should have two levels.

### Level 1: Default permissions by role

Every role has default behavior.

Example:

- Super Admin can do everything.
- Provider Admin can manage most provider-side things.
- Building Manager can manage assigned-building operations.
- Staff can see assigned operational work.
- Customer Company Admin can manage their customer-side scope.
- Customer Location Manager can manage assigned buildings.
- Customer User has limited customer-side access.

These defaults should make the system usable without setting custom permissions for every user.

### Level 2: Custom permission overrides

A user can have custom permissions that override the default.

Custom permissions should be scoped.

A permission should answer:

- Which user?
- Which customer company?
- Which building?
- Which action?
- Is it allowed or denied?

Examples:

- Allow this Building Manager to prepare proposals in Building A.
- Deny this Building Manager from approving on behalf of customers.
- Allow this Customer Location Manager to approve Extra Work only in Building B.
- Deny this Customer User from creating Extra Work.
- Allow this Provider Admin to manage customer permissions.
- Allow Customer Company Admin to manage Customer Users but not create another Customer Company Admin.

### Who can grant permissions?

Simple rule for the current one-provider setup:

Super Admin can grant or remove anything.

Provider Company Admin can manage customer-specific permissions by default.

Super Admin can control whether Provider Company Admin is allowed to manage those permissions.

Provider Admin can grant customer-specific permissions, for example:

- Which customer users can create tickets
- Which customer users can approve proposals
- Which customer users can request Extra Work
- Which Customer Location Managers can manage which buildings
- Which Building Managers can approve/reject on behalf of customers
- Which Building Managers can prepare proposals

Customer Company Admin should have limited permission management only if Provider Admin or Super Admin allows it.

Customer Company Admin must not create another Customer Company Admin by default.

Customer Location Manager should not manage permissions unless explicitly allowed.

Staff should not manage permissions.

### Important permission principle

The UI should show who has access to what in a clear way.

The same saved permissions should be visible in multiple useful places:

- On the Customer Permissions page
- In the user's row after permissions are saved
- In the Customer Users tab
- On the specific user's profile page

The user profile page should first display the user's access rights clearly. Editing should be possible, but viewing should come first.

---

## 6. Ticket workflow

A ticket is normal operational work.

### Normal ticket flow

A simple ticket flow can be:

1. Customer or provider creates a ticket.
2. Provider reviews it.
3. Provider assigns it to a Building Manager or Staff.
4. Staff performs the work.
5. Provider or Building Manager updates the status.
6. If customer approval is needed, the ticket waits for customer approval.
7. Customer approves or rejects.
8. Work is closed or reopened based on the decision.

The exact status names can vary, but the business meaning should stay clear.

Useful statuses:

- Open
- In progress
- Waiting for customer approval
- Approved
- Rejected
- Closed
- Reopened by admin

### Who sees tickets?

Super Admin sees all tickets.

Provider Admin sees provider-scope tickets.

Building Manager sees tickets in assigned buildings.

Staff sees assigned operational tickets/jobs.

Customer Company Admin sees tickets for their customer company.

Customer Location Manager sees tickets for assigned buildings.

Customer User sees tickets in their allowed scope.

### Customer approval in tickets

Sometimes a ticket requires customer approval.

Default rule:

The customer should approve or reject their own customer decision.

But there is an important business exception:

Provider Admin or Building Manager may approve/reject on behalf of the customer when the customer approved outside the system, for example by phone or verbally.

This is allowed by default for Building Manager if the role has the permission, but it must be removable by permissions.

When provider-side users approve/reject on behalf of the customer:

- Show a strong warning in the frontend.
- Require deliberate confirmation.
- Store who performed the action.
- Store that it was done on behalf of the customer.
- Store a reason or note if possible.
- Show it clearly in history/audit.
- Never make it look like the customer personally clicked the button.

Staff should not perform customer approval/rejection.

---

## 7. Extra Work workflow

Extra Work is the most important complex workflow.

Extra Work must support two different paths.

---

## 7.0 Extra Work is always a cart with line items

Extra Work is **always** a cart-like object at the business-logic level. The frontend may later display the cart compactly (e.g. as a one-line summary), but the backend must always represent it as one request containing **one or more line items**. There is no "single-line Extra Work request"; the single-item case is just a cart of length one.

The canonical rules are:

1. A customer creates **one** Extra Work request (the cart).
2. The cart contains **one or more** line items. Each line carries: a Service reference, a unit type, a quantity, a requested date, and optionally a customer note.
3. Each line item is independently classified as either:
   - **Contract-priced for this specific customer** — there is an active `CustomerServicePrice` row for `(this customer, this service, this requested date)` — or
   - **Custom / non-contract** — the resolver returns no contract row for that pair.
4. **Routing rule (whole-cart):** the routing decision is computed once at submission time across the whole cart.
   - If **every** line in the cart resolves to a contract price, the request is routed to the **instant path**: no proposal is required, the customer sees the calculated prices, the customer submits it like an order, and the request enters the operational workflow directly.
   - If **at least one** line in the cart does **not** resolve to a contract price, the whole cart is routed to the **proposal path** — even if the other lines are contract-priced.
5. **In the proposal path**, the contract-priced lines remain represented in the resulting proposal as already-priced lines (their contract price flows through), and provider-side actors add prices and customer-visible explanations for the custom / non-contract lines only. The customer reviews the entire proposal (contract + custom together) and approves or rejects the whole proposal — there is no per-line approve / reject loop at the cart level.
6. **Staff must not see proposal pricing**, provider commercial notes, customer approval controls, or any internal commercial decision data. This applies to both paths.
7. **Staff sees the operational work only after the request / proposal has been approved** and the work has been spawned into one operational ticket / task per cart line. The ticket carries safe operational metadata (parent request id, title, status, service name) but never the pricing or commercial notes.

The cart-first design is permanent: changes that collapse Extra Work back into a single-line concept (or that strip the proposal of its contract-priced lines) violate this section and must be rejected.

---

## 7.1 Path A: Contract-priced Extra Work

This is like buying something from a shopping cart.

The customer already has a contract price for the service.

Example:

Customer A has this contract:

- Window cleaning = EUR 5 per square meter

Customer A wants:

- 50 square meters of window cleaning

The system should show:

- Service: Window cleaning
- Unit price: EUR 5 per square meter
- Quantity: 50 square meters
- Total: EUR 250

The customer can select it, add it to a cart-like request, and submit directly.

There is no need for provider proposal preparation because the price is already agreed in the contract.

This should behave like:

1. Customer opens Extra Work request.
2. Customer sees available contract-priced services for their company.
3. Customer adds one or more line items, like a cart.
4. Each line has service, unit type, quantity, unit price, and total.
5. Customer sees total price before submitting.
6. Customer submits.
7. The request goes directly into provider operations.
8. Provider schedules/assigns it.
9. Staff sees it only when it becomes assigned operational work.

Important:

The customer must only see contract-priced services that are valid for their customer company.

If the customer company does not have a contract price for that service, it should not be treated as direct fixed-price work.

### Multiple line items

Extra Work should allow multiple line items.

Example:

- 50 square meters window cleaning
- 2 hours deep cleaning
- 1 special floor treatment

The customer should be able to add items like a cart.

The frontend must not force everything into one confusing line. The business concept is still a cart, even if the UI later chooses a compact layout.

---

## 7.2 Path B: Non-contract Extra Work that needs proposal

This is for work that is not already priced in the customer's contract.

Example:

Customer A does not have grass cutting in their contract.

Customer A requests:

- "I want 100 square meters of grass cutting."

Then the provider must prepare a proposal.

Flow:

1. Customer requests custom Extra Work.
2. Provider Admin or allowed Building Manager sees the request.
3. Provider prepares a price proposal.
4. Proposal can contain multiple line items.
5. Provider sends the proposal to customer.
6. Customer reviews customer-visible proposal details.
7. Customer approves or rejects.
8. If approved, the work becomes operational work and can be assigned to staff.
9. Staff sees only the assigned operational work, not pricing/proposal/internal financial notes.

### Proposal statuses

Proposal statuses should mean:

- Draft: Provider is preparing it. Customer should not see it.
- Sent: Customer can see it and decide.
- Approved: Customer accepted it, or provider-side user approved on behalf of customer with audit.
- Rejected: Customer rejected it, or provider-side user rejected on behalf of customer with audit.
- Cancelled: Provider cancelled it.
- Expired: Optional future status if proposal deadlines are added.

### Who can prepare proposals?

Super Admin can prepare proposals.

Provider Admin can prepare proposals.

Building Manager can prepare proposals by default for assigned buildings.

Permissions can remove proposal preparation from a Building Manager.

Staff should not prepare proposals.

Customer users should not prepare provider proposals.

### Who can approve/reject proposals?

Customer Company Admin can approve/reject for their customer company if allowed.

Customer Location Manager can approve/reject for assigned buildings if allowed.

Customer User can approve/reject only if explicitly allowed.

Provider Admin can approve/reject on behalf of the customer when the customer approved outside the system, if allowed.

Building Manager can approve/reject on behalf of the customer by default for assigned buildings, if allowed by permissions.

When provider-side users approve/reject on behalf of a customer, the same warning/audit rules apply:

- Warning
- Confirmation
- Reason/note
- Audit/history
- Clear "on behalf of customer" label

Staff cannot approve/reject proposals.

---

## 8. Pricing and Services

The Services page should manage the general catalog of services.

Example services:

- Window cleaning
- Grass cutting
- Deep cleaning
- Floor polishing

The Pricing page should manage customer-specific contract prices.

A service alone does not mean every customer can order it at a fixed price.

A customer-specific price is what makes a service available for direct contract-priced Extra Work.

Each customer should have its own contract-price setup.

Example:

Customer A:
- Window cleaning: EUR 5 per square meter
- Deep cleaning: EUR 40 per hour

Customer B:
- Grass cutting: EUR 2 per square meter
- Window cleaning: not contracted, proposal required

The customer detail area should allow provider admins to enter and manage that customer's contract prices.

The customer-specific pricing must be clear enough that the frontend can show:

- Which services are available directly for this customer
- The unit price
- The unit type
- Whether approval/proposal is needed
- Whether the price is active

---

## 9. Notes and visibility

The system needs different types of notes.

Do not treat every internal note as the same thing.

### Customer-visible comment

Visible to customer and provider.

Used for normal communication.

Example:

"The work is planned for Friday."

### Provider-only internal note

Visible only to provider-side management roles that are allowed to see it.

Not visible to customers.

Usually not visible to staff if it contains financial or management information.

Example:

"Our cost is EUR 120."
"Margin is low."
"Customer is difficult with payments."

### Staff-visible operational note

Visible to staff and provider-side operations.

Not visible to customers.

Can be visible to Building Manager.

Example:

"Bring stronger cleaning material."
"Use the back entrance."
"Windows are very dirty."
"Bring ladder."

### Provider management note excluding staff

Visible to Super Admin, Provider Admin, maybe Building Manager if allowed.

Not visible to staff.

Not visible to customer.

Example:

"Do not discount this request."
"Discuss pricing with Ramazan first."

### Suggested product rule

Notes should have a visibility/type field, not just one generic internal_note.

At minimum:

- Public/customer-visible
- Provider-only management
- Staff-visible operational
- Provider-only excluding staff

This can be implemented as ticket/proposal/message note type rather than only as a permission checkbox.

---

## 10. What each role should see

### Super Admin dashboard

Should see the whole system.

- All active tickets
- All Extra Work
- Approval queues
- Urgent work
- Customer/company overview
- System settings
- Permissions
- Pricing
- Services
- Users

### Provider Admin dashboard

Should see provider operations.

- Tickets
- Extra Work
- Pending proposals
- Customer approval queue
- Staff workload
- Building workload
- Customer-specific pricing
- Services
- Customer users/contacts
- Permissions they are allowed to manage

### Building Manager dashboard

Should see assigned-building operations.

- Tickets for assigned buildings
- Extra Work for assigned buildings
- Work needing scheduling/assignment
- Proposal preparation if allowed
- Approval/rejection on behalf of customer if allowed
- Staff operational status for assigned buildings

Should not see unassigned buildings.

### Staff dashboard

Should see only operational work assigned to them.

- Assigned tickets/jobs
- Location
- Description
- Staff-visible notes
- Attachments needed for work
- Operational status updates

Should not see proposal/pricing/customer approval controls.

### Customer Company Admin dashboard

Should see customer-company work.

- Tickets for their company
- Extra Work requests
- Proposals waiting for approval
- Contract-priced services
- Customer-visible prices
- Customer users if allowed
- Customer buildings

### Customer Location Manager dashboard

Should see assigned buildings.

- Tickets for assigned buildings
- Extra Work for assigned buildings
- Proposals/approvals for assigned buildings if allowed
- Customer-visible prices for assigned buildings if relevant

### Customer User dashboard

Should see limited customer-side work.

- Tickets they can see
- Extra Work they can request or view
- Customer-visible comments
- Their allowed buildings

---

## 11. Customer detail pages

When a provider admin opens a customer, the customer-specific pages should be meaningful.

### Overview

Shows the customer relationship:

- Customer name
- Provider company
- Active/inactive status
- Linked buildings
- Contacts
- Users
- Pricing rules
- Quick links to management areas

### Buildings

Shows which buildings this customer is linked to.

This matters because tickets and Extra Work can only be created for valid customer-building combinations.

### Users

Shows customer users.

Each row should clearly show what the user can access.

Saved permissions should be visible here after they are saved.

This page should display first, then allow editing.

### Permissions

Shows detailed access and permission controls.

This is where admins tune user access by customer/building/action.

### Pricing

Shows customer-specific contract prices.

This is where the provider enters the customer's agreed prices for services.

This page is essential for contract-priced Extra Work.

### Services

Services are the provider's general catalog.

Services are not the same as customer-specific prices.

### Extra Work

Customer-specific Extra Work page should eventually show:

- Direct contract-priced Extra Work available to this customer
- Non-contract requests
- Proposals
- Approval state
- History

If currently empty, it must be filled later.

### Settings

Shows customer-wide settings such as visibility preferences and lifecycle actions.

---

## 12. Audit and history rules

Important actions must be traceable.

The system should store:

- Who did the action
- What they did
- When they did it
- Which role they had
- Whether they acted on behalf of a customer
- Why they acted on behalf of a customer, if applicable
- Before/after state where useful

Actions that must be audited:

- Permission changes
- Customer approval/rejection
- Provider-side approval/rejection on behalf of customer
- Proposal sent
- Proposal approved/rejected/cancelled
- Ticket status changes
- Assignment changes
- Pricing changes
- Customer-building membership changes
- User membership changes

---

## 13. Non-negotiable privacy rules

Customers must not see:

- Provider internal financial notes
- Provider cost/margin information
- Internal staff/management notes
- Other customer companies
- Buildings outside their scope
- Users outside their scope

Staff must not see:

- Proposal pricing
- Customer approval controls
- Provider financial notes
- Customer contract management
- Permissions management

Building Managers must not see:

- Unassigned buildings
- Provider-wide settings
- Customer user permission management by default, unless explicitly allowed
- Provider-only financial notes unless explicitly allowed

Provider-side users must not silently pretend to be customer users.

If they approve/reject on behalf of a customer, the system must show and store that clearly.

---

## 14. What developers should do next

Before implementing new frontend polish, the backend rules should be checked against this document.

Recommended order:

1. Check current backend role visibility.
2. Check current ticket workflow.
3. Check current Extra Work workflow.
4. Check contract-priced Extra Work support.
5. Check non-contract proposal workflow.
6. Check customer-specific pricing.
7. Check note visibility types.
8. Check permission overrides.
9. Check who can grant which permissions.
10. Check audit/history for approval-on-behalf-of-customer.
11. Only after backend behavior is correct, polish the frontend.

---

## 15. Instructions for Claude Code or any AI developer

Read this document first.

Then inspect the current repository yourself.

Do not assume the code already matches this document.

Do not invent new product rules.

Do not redesign the frontend before checking backend behavior.

Do not make huge mixed changes.

First produce a report with these sections:

1. What already matches this document.
2. What conflicts with this document.
3. What is missing.
4. What backend changes are required.
5. What frontend changes are required later.
6. Which changes need migrations.
7. Which changes need tests.
8. Which changes are risky and should be split into separate batches.

If you do not know how something should work, do not guess. Search the code and docs first. If it is still unclear, ask.

Backend should be made correct first.

Frontend should then be made premium, clear, and easy to use based on the corrected backend behavior.

Screenshots can be provided for pages that look wrong, but the developer should also inspect the frontend directly and propose easier review methods, such as:

- Running the app locally
- Using Playwright screenshots
- Creating a visual route inventory
- Listing empty/placeholder pages
- Listing pages with broken UX
- Creating a before/after screenshot folder
- Creating a frontend audit document

---

## 16. One-sentence summary

The system is a provider-company operations platform where customer companies request normal tickets and Extra Work, customer-specific contract prices allow direct cart-like Extra Work ordering, non-contract work needs provider proposals, roles have default permissions plus custom overrides, provider-side users may act on behalf of customers only with warning and audit, and staff only see assigned operational work after approval, never pricing or provider-only notes.
