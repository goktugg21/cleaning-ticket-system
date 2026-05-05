import type { FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getApiError } from "../api/client";
import type { AdminFieldErrors } from "../api/admin";
import { extractAdminFieldErrors } from "../api/admin";

export interface UseEntityFormConfig<TEntity, TPayload> {
  id: string | undefined;
  fetchFn: (id: number) => Promise<TEntity>;
  createFn?: (payload: TPayload) => Promise<TEntity>;
  updateFn: (id: number, payload: TPayload) => Promise<TEntity>;
  buildPayload: () => TPayload;
  applyEntity: (entity: TEntity) => void;
  successPath: (entity: TEntity, isCreate: boolean) => string;
  onEditSuccess?: (entity: TEntity) => void;
  // Optional client-side check that runs before buildPayload. Returning a
  // non-empty record short-circuits submission and surfaces the errors as
  // fieldErrors. Used by the build/customer pages to gate on parent-id
  // selection in create mode without doing a round-trip to the API.
  validate?: () => AdminFieldErrors | null;
}

export interface UseEntityFormResult<TEntity> {
  entity: TEntity | null;
  setEntity: (entity: TEntity | null) => void;
  isCreate: boolean;
  numericId: number | null;
  loading: boolean;
  submitting: boolean;
  generalError: string;
  setGeneralError: (message: string) => void;
  fieldErrors: AdminFieldErrors;
  handleSubmit: (event: FormEvent) => Promise<void>;
  reload: () => Promise<void>;
}

export function useEntityForm<TEntity, TPayload>(
  config: UseEntityFormConfig<TEntity, TPayload>,
): UseEntityFormResult<TEntity> {
  const navigate = useNavigate();
  const isCreate = config.id === undefined;
  const numericId = isCreate ? null : Number(config.id);

  const [entity, setEntity] = useState<TEntity | null>(null);
  const [loading, setLoading] = useState(!isCreate);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  // Hold the latest config in a ref so the load effect and handleSubmit are
  // stable across page renders. Pages construct the config inline (so its
  // identity changes every render); without this indirection the load effect
  // would resubscribe on every render and cancel its own fetch in flight.
  const configRef = useRef(config);
  configRef.current = config;

  const runFetch = useCallback(
    async (signal: { cancelled: boolean }) => {
      if (numericId === null || !Number.isFinite(numericId)) return;
      setLoading(true);
      try {
        const data = await configRef.current.fetchFn(numericId);
        if (signal.cancelled) return;
        setEntity(data);
        configRef.current.applyEntity(data);
      } catch (err) {
        if (!signal.cancelled) setGeneralError(getApiError(err));
      } finally {
        if (!signal.cancelled) setLoading(false);
      }
    },
    [numericId],
  );

  useEffect(() => {
    if (isCreate) return;
    const signal = { cancelled: false };
    runFetch(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [isCreate, runFetch]);

  const reload = useCallback(async () => {
    const signal = { cancelled: false };
    await runFetch(signal);
  }, [runFetch]);

  const handleSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      setGeneralError("");
      setFieldErrors({});
      const cfg = configRef.current;
      const validationErrors = cfg.validate?.();
      if (validationErrors && Object.keys(validationErrors).length > 0) {
        setFieldErrors(validationErrors);
        return;
      }
      setSubmitting(true);
      try {
        const payload = cfg.buildPayload();
        if (isCreate) {
          if (!cfg.createFn) {
            throw new Error("createFn is required when id is undefined");
          }
          const created = await cfg.createFn(payload);
          navigate(cfg.successPath(created, true), { replace: true });
          return;
        }
        if (numericId === null) return;
        const updated = await cfg.updateFn(numericId, payload);
        setEntity(updated);
        cfg.applyEntity(updated);
        cfg.onEditSuccess?.(updated);
      } catch (err) {
        const fields = extractAdminFieldErrors(err);
        if (Object.keys(fields).length > 0) {
          setFieldErrors(fields);
          if (fields.detail) setGeneralError(fields.detail);
        } else {
          setGeneralError(getApiError(err));
        }
      } finally {
        setSubmitting(false);
      }
    },
    [isCreate, numericId, navigate],
  );

  return {
    entity,
    setEntity,
    isCreate,
    numericId,
    loading,
    submitting,
    generalError,
    setGeneralError,
    fieldErrors,
    handleSubmit,
    reload,
  };
}
