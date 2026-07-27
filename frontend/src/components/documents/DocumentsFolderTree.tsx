// Sprint 126 — the folder tree for the Documents explorer. Recursive rows
// with select + native HTML5 drag/drop (a file or folder dropped on a folder
// row moves it there; the server enforces cycle/depth). System folders are
// visually distinct. Folder mutations live in the explorer toolbar, not here.
import { Folder, FolderLock, FolderOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DocumentFolder } from "../../api/types";
import {
  DND_MIME,
  folderAndDescendantIds,
  type DndPayload,
  type DocumentsSide,
  type FolderNode,
  canMoveOrDeleteFolder,
} from "./documentsAccess";

interface FolderTreeProps {
  side: DocumentsSide;
  tree: FolderNode[];
  allFolders: DocumentFolder[];
  selectedFolderId: number | null;
  dragging: DndPayload | null;
  onSelect: (id: number) => void;
  onDragStart: (payload: DndPayload) => void;
  onDragEnd: () => void;
  onDropOnFolder: (targetFolderId: number, payload: DndPayload) => void;
}

function isValidDropTarget(
  dragging: DndPayload | null,
  target: DocumentFolder,
  allFolders: DocumentFolder[],
): boolean {
  if (!dragging) return false;
  if (dragging.kind === "folder") {
    const draggedId = Number(dragging.id);
    if (draggedId === target.id) return false;
    if (folderAndDescendantIds(allFolders, draggedId).has(target.id)) {
      return false; // no cycle
    }
  }
  return true;
}

export function DocumentsFolderTree({
  side,
  tree,
  allFolders,
  selectedFolderId,
  dragging,
  onSelect,
  onDragStart,
  onDragEnd,
  onDropOnFolder,
}: FolderTreeProps) {
  const { t } = useTranslation("common");

  const renderNode = (node: FolderNode, depth: number) => {
    const selected = node.id === selectedFolderId;
    const draggable = canMoveOrDeleteFolder(side, node);
    const droppable = isValidDropTarget(dragging, node, allFolders);
    const isDragged =
      dragging?.kind === "folder" && Number(dragging.id) === node.id;

    const Icon = node.is_system ? FolderLock : selected ? FolderOpen : Folder;

    return (
      <div key={node.id} role="treeitem" aria-selected={selected}>
        <button
          type="button"
          className={[
            "doc-tree-row",
            selected ? "doc-tree-row-selected" : "",
            node.is_system ? "doc-tree-row-system" : "",
            droppable ? "doc-tree-row-drop" : "",
            isDragged ? "doc-tree-row-dragging" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={{ paddingLeft: 8 + depth * 16 }}
          data-testid="doc-tree-row"
          data-folder-id={node.id}
          data-system={node.is_system ? "true" : "false"}
          onClick={() => onSelect(node.id)}
          draggable={draggable}
          onDragStart={(event) => {
            const payload: DndPayload = { kind: "folder", id: String(node.id) };
            event.dataTransfer.setData(DND_MIME, JSON.stringify(payload));
            event.dataTransfer.effectAllowed = "move";
            onDragStart(payload);
          }}
          onDragEnd={onDragEnd}
          onDragOver={(event) => {
            if (droppable) event.preventDefault();
          }}
          onDrop={(event) => {
            event.preventDefault();
            const raw = event.dataTransfer.getData(DND_MIME);
            if (!raw) return;
            try {
              onDropOnFolder(node.id, JSON.parse(raw) as DndPayload);
            } catch {
              // ignore a malformed payload
            }
          }}
        >
          <span className="doc-tree-icon" aria-hidden="true">
            <Icon size={16} strokeWidth={1.9} />
          </span>
          <span className="doc-tree-name">{node.name}</span>
          {node.is_system && (
            <span className="doc-tree-badge">
              {t("documents.system_badge")}
            </span>
          )}
        </button>
        {node.children.length > 0 && (
          <div role="group">
            {node.children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="doc-tree" role="tree" aria-label={t("documents.tree_label")}>
      {tree.map((node) => renderNode(node, 0))}
    </div>
  );
}
