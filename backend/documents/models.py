"""
Sprint 125 — Customer Documents.

A per-customer document store: a folder tree plus files, shared between
the provider (SUPER_ADMIN / COMPANY_ADMIN) and the customer's own users.
The two-sided ownership is carried by `origin` (PROVIDER | CUSTOMER),
stamped from the ACTOR'S ROLE at write time and immutable thereafter — it
decides who may later rename / move / delete a row, and must NOT be
re-derived from `uploaded_by` / `created_by` at read time (a user's role
can change, which would silently flip who owns a contract).

Four `is_system` root folders (Facturen / Contracten / Overeenkomsten /
Overig) are auto-created per customer via a post_save signal on Customer
(see `documents/signals.py`) and back-filled for existing customers by a
data migration. Their display name is renamable (provider only) but their
`system_slug` never changes — Phase 2 auto-files generated invoices into
the `facturen` slug.
"""
from __future__ import annotations

import uuid
from pathlib import Path as FilePath

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


# The four default system folders created for every customer. The slug is
# the STABLE identifier (Phase 2 files invoices into "facturen"); the name
# is the initial display label and may be renamed by the provider.
SYSTEM_FOLDER_SPECS: tuple[tuple[str, str], ...] = (
    ("facturen", "Facturen"),
    ("contracten", "Contracten"),
    ("overeenkomsten", "Overeenkomsten"),
    ("overig", "Overig"),
)

# Server-side nesting cap, enforced on create AND move. Root folders sit at
# depth 1, so a chain root→…→leaf may be at most this many folders deep.
MAX_FOLDER_DEPTH = 10


class DocumentOrigin(models.TextChoices):
    """Who a folder / file belongs to. Stamped from the actor's role at
    write time; decides customer-side write eligibility (a customer user
    may only mutate CUSTOMER-origin rows). Immutable after create."""

    PROVIDER = "PROVIDER", "Provider"
    CUSTOMER = "CUSTOMER", "Customer"


def document_upload_path(instance, filename):
    """Storage path for an uploaded document. Mirrors
    `tickets.ticket_attachment_upload_path`: a per-customer directory + an
    opaque uuid filename (the original name is preserved on the model in
    `original_filename`, never in the storage path)."""
    extension = FilePath(filename).suffix.lower()
    return f"documents/{instance.customer_id}/{uuid.uuid4().hex}{extension}"


class DocumentFolder(models.Model):
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="document_folders",
    )
    # NULL parent = a root folder. A self-FK on PROTECT would block deleting
    # a folder that still has children; we enforce empty-only delete in the
    # view instead and CASCADE here so a (rare, never-exposed) programmatic
    # subtree removal stays consistent.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    name = models.CharField(max_length=255)
    is_system = models.BooleanField(default=False)
    # Blank for user folders; one of SYSTEM_FOLDER_SPECS' slugs for the four
    # default folders. Never changes once set (Phase 2 keys off it).
    system_slug = models.CharField(max_length=64, blank=True, default="")
    origin = models.CharField(
        max_length=16,
        choices=DocumentOrigin.choices,
    )
    # Nullable: system folders (signal / backfill) are system writes with no
    # actor. PROTECT still prevents deleting a user who created folders.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_document_folders",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            # Case-insensitive name uniqueness per (customer, parent).
            # TWO partial constraints because Postgres treats NULLs as
            # DISTINCT: a single UniqueConstraint over a nullable `parent`
            # would let two root folders share a name. The precedent for a
            # Lower()-based unique constraint is extra_work/0018.
            models.UniqueConstraint(
                "customer",
                Lower("name"),
                condition=Q(parent__isnull=True),
                name="uniq_doc_folder_root_name_per_customer_ci",
            ),
            models.UniqueConstraint(
                "customer",
                "parent",
                Lower("name"),
                condition=Q(parent__isnull=False),
                name="uniq_doc_folder_child_name_per_parent_ci",
            ),
        ]

    def __str__(self):
        return f"{self.customer_id} / {self.name}"

    # -- tree helpers (all bounded by MAX_FOLDER_DEPTH so they stay cheap) --

    def ancestors(self) -> list["DocumentFolder"]:
        """Return [parent, grandparent, …] up to the root. Bounded by the
        depth cap so a corrupt cycle cannot loop forever."""
        chain: list[DocumentFolder] = []
        node = self.parent
        guard = 0
        while node is not None and guard <= MAX_FOLDER_DEPTH + 1:
            chain.append(node)
            node = node.parent
            guard += 1
        return chain

    def depth(self) -> int:
        """1 for a root folder, +1 per ancestor."""
        return 1 + len(self.ancestors())

    def descendant_ids(self) -> set[int]:
        """All descendant folder ids (excludes self). One query per level,
        bounded by the depth cap."""
        collected: set[int] = set()
        frontier = [self.id]
        guard = 0
        while frontier and guard <= MAX_FOLDER_DEPTH + 1:
            child_ids = list(
                DocumentFolder.objects.filter(parent_id__in=frontier).values_list(
                    "id", flat=True
                )
            )
            child_ids = [cid for cid in child_ids if cid not in collected]
            collected.update(child_ids)
            frontier = child_ids
            guard += 1
        return collected

    def subtree_height(self) -> int:
        """Number of levels in this folder's own subtree: 1 if it has no
        children, 2 if it has children but no grandchildren, etc. Used to
        keep a MOVE within the depth cap for the deepest moved node."""
        height = 1
        frontier = [self.id]
        guard = 0
        while frontier and guard <= MAX_FOLDER_DEPTH + 1:
            child_ids = list(
                DocumentFolder.objects.filter(parent_id__in=frontier).values_list(
                    "id", flat=True
                )
            )
            if not child_ids:
                break
            height += 1
            frontier = child_ids
            guard += 1
        return height


class Document(models.Model):
    # The ONLY identifier that appears in an API path (never the row pk).
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    folder = models.ForeignKey(
        DocumentFolder,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    # Denormalized from `folder.customer` for direct tenant scoping without a
    # join. Invariant (asserted in tests + enforced on write): it ALWAYS
    # equals folder.customer.
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file = models.FileField(upload_to=document_upload_path)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    file_size = models.PositiveIntegerField()
    origin = models.CharField(
        max_length=16,
        choices=DocumentOrigin.choices,
    )
    # Nullable + PROTECT for the same reasons as DocumentFolder.created_by:
    # Phase 2 will auto-file provider invoice PDFs as system writes (no
    # actor), and PROTECT still guards a referenced user against deletion.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        return self.original_filename
