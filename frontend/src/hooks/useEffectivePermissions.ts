import { useEffect, useState } from "react";

import {
  fetchEffectivePermissions,
  type EffectiveActions,
  type EffectivePermissionsResponse,
} from "../api/effectivePermissions";
import { getApiError } from "../api/client";

// React hook around the admin permission-overview endpoint
// (GET /api/users/<id>/effective-permissions/).
//
// Caller-authorization constraint repeated for any reader:
//   The endpoint only admits SUPER_ADMIN and COMPANY_ADMIN. BM / STAFF /
//   CUSTOMER_USER will receive 403 (surfaced as `error`). Use this hook
//   from admin screens only. For non-admin runtime gating, derive from
//   `Me.role` + scope ids via predicates in `auth/permissions.ts`.
//
// The hook re-fetches whenever (userId, customerId, buildingId) changes.
// A signal-aware abort drops in-flight responses if the inputs change
// faster than the network. `null` userId / customerId pauses the call.

export interface UseEffectivePermissionsArgs {
  userId: number | null;
  customerId: number | null;
  buildingId?: number | null;
}

export interface UseEffectivePermissionsResult {
  data: EffectivePermissionsResponse | null;
  effectiveActions: EffectiveActions | null;
  loading: boolean;
  error: string | null;
}

export function useEffectivePermissions(
  args: UseEffectivePermissionsArgs,
): UseEffectivePermissionsResult {
  const { userId, customerId } = args;
  const buildingId = args.buildingId ?? null;

  const [data, setData] = useState<EffectivePermissionsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (userId == null || customerId == null) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchEffectivePermissions({
      userId,
      customerId,
      buildingId,
      signal: controller.signal,
    })
      .then((response) => {
        if (cancelled) return;
        setData(response);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [userId, customerId, buildingId]);

  return {
    data,
    effectiveActions: data?.effective_actions ?? null,
    loading,
    error,
  };
}
