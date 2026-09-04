// RF-1 — a shared avatar/logo upload control: current image (or initials
// fallback) + Upload/Replace + Remove. The parent owns the current URL
// and supplies onUpload/onRemove; on success the parent updates its URL
// (a new ?v= marker) so the Avatar refetches exactly once.
//
// P-8R D — the "badge" variant is the same control folded into an
// avatar: a pencil badge on the avatar opens the file picker, a quiet
// text link underneath removes the photo. Same inputs, same test ids,
// same upload and delete paths; only the chrome differs.
import { Pencil } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import { Avatar } from "./Avatar";

export function ImageUploadField({
  imageUrl,
  name,
  onUpload,
  onRemove,
  rounded = true,
  size = 88,
  disabled = false,
  testId = "image-upload",
  variant = "default",
}: {
  imageUrl?: string | null;
  name?: string | null;
  onUpload: (file: File) => Promise<void>;
  onRemove: () => Promise<void>;
  rounded?: boolean;
  size?: number;
  disabled?: boolean;
  testId?: string;
  variant?: "default" | "badge";
}) {
  const { t } = useTranslation("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await onUpload(file);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleRemove() {
    setBusy(true);
    setError("");
    try {
      await onRemove();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      accept="image/jpeg,image/png,image/webp"
      hidden
      onChange={handleFile}
      data-testid={`${testId}-input`}
    />
  );

  if (variant === "badge") {
    return (
      <div className="image-upload-badge" data-testid={testId}>
        <span className="image-upload-badge-avatar">
          <Avatar imageUrl={imageUrl} name={name} size={size} rounded={rounded} />
          {fileInput}
          <button
            type="button"
            className="image-upload-badge-btn"
            onClick={() => inputRef.current?.click()}
            disabled={busy || disabled}
            aria-label={t("image_upload.change_photo")}
            title={t("image_upload.change_photo")}
            data-testid={`${testId}-upload`}
          >
            <Pencil size={12} strokeWidth={2.4} aria-hidden="true" />
          </button>
        </span>
        {imageUrl && (
          <button
            type="button"
            className="image-upload-badge-remove"
            onClick={handleRemove}
            disabled={busy || disabled}
            data-testid={`${testId}-remove`}
          >
            {t("image_upload.remove_photo")}
          </button>
        )}
        {error && (
          <div className="alert-error" role="alert" style={{ marginTop: 6 }}>
            {error}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="image-upload-field" data-testid={testId}>
      <Avatar imageUrl={imageUrl} name={name} size={size} rounded={rounded} />
      <div className="image-upload-body">
        <div className="image-upload-actions">
          {fileInput}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => inputRef.current?.click()}
            disabled={busy || disabled}
            data-testid={`${testId}-upload`}
          >
            {imageUrl
              ? t("image_upload.replace")
              : t("image_upload.upload")}
          </button>
          {imageUrl && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleRemove}
              disabled={busy || disabled}
              data-testid={`${testId}-remove`}
            >
              {t("image_upload.remove")}
            </button>
          )}
        </div>
        <p className="image-upload-hint muted">{t("image_upload.hint")}</p>
        {error && (
          <div className="alert-error" role="alert" style={{ marginTop: 6 }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
