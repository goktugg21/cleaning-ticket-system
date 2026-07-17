/**
 * RF-1 — one shared avatar renderer.
 *
 * Given an authed image URL (profile photo or customer/company logo) it
 * fetches the blob through the module-level cache and shows the image;
 * on absence or failure it falls back to deterministic-colour initials.
 * A small second avatar can be overlaid (the inbox rows show the last
 * author's photo over the customer logo).
 */
import { useEffect, useState } from "react";

import { getAvatarObjectUrl } from "../lib/avatarBlobCache";
import { avatarColor } from "../lib/avatarColor";
import { getInitials } from "../lib/initials";

// Resolve an authed image URL to a cached object URL. All setState runs
// inside an async function (never synchronously in the effect body), so
// this does not trip the no-cascading-render rule.
function useAvatarObjectUrl(url: string | null | undefined): string | null {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!url) {
        if (!cancelled) setObjectUrl(null);
        return;
      }
      const resolved = await getAvatarObjectUrl(url);
      if (!cancelled) setObjectUrl(resolved);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [url]);
  return objectUrl;
}

export function Avatar({
  imageUrl,
  name,
  size = 40,
  rounded = true,
  className,
}: {
  imageUrl?: string | null;
  name?: string | null;
  size?: number;
  rounded?: boolean;
  className?: string;
}) {
  const objectUrl = useAvatarObjectUrl(imageUrl);
  const style: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: rounded ? "50%" : "18%",
    fontSize: Math.round(size * 0.4),
  };
  const classes = `avatar${className ? ` ${className}` : ""}`;

  if (objectUrl) {
    return (
      <img
        src={objectUrl}
        alt={name ?? ""}
        className={classes}
        style={style}
        draggable={false}
      />
    );
  }
  return (
    <span
      className={`${classes} avatar-fallback`}
      style={{ ...style, background: avatarColor(name) }}
      aria-label={name ?? undefined}
    >
      {getInitials(name)}
    </span>
  );
}

/**
 * The inbox row avatar: the customer logo (or its initials) with the
 * last author's small photo overlaid bottom-right.
 */
export function InboxThreadAvatar({
  logoUrl,
  customerName,
  authorPhotoUrl,
  authorName,
  size = 44,
}: {
  logoUrl?: string | null;
  customerName?: string | null;
  authorPhotoUrl?: string | null;
  authorName?: string | null;
  size?: number;
}) {
  return (
    <span
      className="inbox-thread-avatar"
      style={{ width: size, height: size }}
    >
      <Avatar
        imageUrl={logoUrl}
        name={customerName}
        size={size}
        rounded={false}
      />
      <span className="inbox-thread-avatar-overlay">
        <Avatar
          imageUrl={authorPhotoUrl}
          name={authorName}
          size={Math.round(size * 0.5)}
        />
      </span>
    </span>
  );
}
