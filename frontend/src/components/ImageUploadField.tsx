// RF-1 — a shared avatar/logo upload control: current image (or initials
// fallback) + Upload/Replace + Remove. The parent owns the current URL
// and supplies onUpload/onRemove; on success the parent updates its URL
// (a new ?v= marker) so the Avatar refetches exactly once.
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
}: {
  imageUrl?: string | null;
  name?: string | null;
  onUpload: (file: File) => Promise<void>;
  onRemove: () => Promise<void>;
  rounded?: boolean;
  size?: number;
  disabled?: boolean;
  testId?: string;
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

  return (
    <div className="image-upload-field" data-testid={testId}>
      <Avatar imageUrl={imageUrl} name={name} size={size} rounded={rounded} />
      <div className="image-upload-body">
        <div className="image-upload-actions">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={handleFile}
            data-testid={`${testId}-input`}
          />
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
