import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import type {
  Gallery, Health, Outfit, Profile, ProfileInput, ReplacementInput,
  RequestInput, RequestState,
} from '../types';

const EMPTY_GALLERY: Gallery = { outfits: [], products: [] };
const messageOf = (error: unknown) => error instanceof ApiError
  ? error.message : 'Не удалось выполнить действие. Попробуйте ещё раз.';
const isAborted = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

/** Request state is scoped by ID and operation epoch; late reads cannot undo an edit. */
export function useVelor() {
  const [health, setHealth] = useState<Health | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [gallery, setGallery] = useState<Gallery>(EMPTY_GALLERY);
  const [request, setRequest] = useState<RequestState | null>(null);
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const scopeEpoch = useRef(0);
  const operationEpoch = useRef(0);
  const galleryEpoch = useRef(0);
  const requestRef = useRef<RequestState | null>(null);
  const busyRef = useRef<string | null>(null);
  const bootingRef = useRef(true);
  const bootController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);

  const setCurrentRequest = useCallback((next: RequestState) => {
    requestRef.current = next;
    setRequest(next);
  }, []);

  const applyOutfit = useCallback((next: Outfit) => {
    const current = requestRef.current;
    if (!current || current.id !== next.request_id) return;
    setCurrentRequest({
      ...current,
      outfits: current.outfits.map((outfit) => outfit.id === next.id && outfit.revision <= next.revision ? next : outfit),
    });
  }, [setCurrentRequest]);

  const refreshGallery = useCallback(async () => {
    const epoch = ++galleryEpoch.current;
    const scope = scopeEpoch.current;
    try {
      const next = await api.gallery();
      if (mounted.current && epoch === galleryEpoch.current && scope === scopeEpoch.current) setGallery(next);
    } catch (caught) {
      if (mounted.current && epoch === galleryEpoch.current && scope === scopeEpoch.current && !isAborted(caught)) {
        setError(messageOf(caught));
      }
    }
  }, []);

  const reload = useCallback(async () => {
    const scope = ++scopeEpoch.current;
    const epoch = ++operationEpoch.current;
    const galleryVersion = ++galleryEpoch.current;
    bootController.current?.abort();
    mutationController.current?.abort();
    const controller = new AbortController();
    bootController.current = controller;
    busyRef.current = null;
    bootingRef.current = true;
    setBusy(null);
    setBooting(true);
    setError(null);
    const currentId = requestRef.current?.id;
    const results = await Promise.allSettled([
      api.health(controller.signal),
      api.profile(controller.signal),
      api.gallery(controller.signal),
      currentId ? api.request(currentId, controller.signal) : Promise.resolve(null),
    ]);
    if (!mounted.current || scope !== scopeEpoch.current || controller.signal.aborted) return;
    const [healthResult, profileResult, galleryResult, requestResult] = results;
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
    if (profileResult.status === 'fulfilled') setProfile(profileResult.value);
    if (galleryResult.status === 'fulfilled' && galleryVersion === galleryEpoch.current) setGallery(galleryResult.value);
    if (requestResult.status === 'fulfilled' && requestResult.value && epoch === operationEpoch.current) {
      setCurrentRequest(requestResult.value);
    }
    const failed = results.find((result) => result.status === 'rejected');
    if (failed?.status === 'rejected' && !isAborted(failed.reason)) setError(messageOf(failed.reason));
    setBooting(false);
    bootingRef.current = false;
  }, [setCurrentRequest]);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    return () => {
      cancelled = true;
      mounted.current = false;
      bootController.current?.abort();
      mutationController.current?.abort();
    };
  }, [reload]);

  const pendingRender = request?.outfits.some((outfit) => outfit.render_status === 'pending') ?? false;
  const requestId = request?.id;
  const requestStatus = request?.status;

  useEffect(() => {
    if (!requestId || !(requestStatus === 'searching' || requestStatus === 'styling' || pendingRender)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    let pollingError: string | null = null;
    const poll = async () => {
      const epoch = operationEpoch.current;
      const scope = scopeEpoch.current;
      if (!busyRef.current && !bootingRef.current) {
        try {
          const next = await api.request(requestId, controller.signal);
          if (!stopped && mounted.current && scope === scopeEpoch.current && epoch === operationEpoch.current
              && requestRef.current?.id === requestId && !busyRef.current) {
            // A cached or delayed response must never reduce a known outfit revision.
            const known = new Map(requestRef.current.outfits.map((outfit) => [outfit.id, outfit]));
            const outfits = next.outfits.map((outfit) => {
              const previous = known.get(outfit.id);
              return previous && previous.revision > outfit.revision ? previous : outfit;
            });
            setCurrentRequest({ ...next, outfits });
            if (pollingError) {
              const recovered = pollingError;
              setError((current) => current === recovered ? null : current);
              pollingError = null;
            }
          }
        } catch (caught) {
          if (!stopped && mounted.current && !controller.signal.aborted && !isAborted(caught)
              && scope === scopeEpoch.current && epoch === operationEpoch.current) {
            pollingError = messageOf(caught);
            setError(pollingError);
          }
        }
      }
      if (!stopped) timer = setTimeout(() => { void poll(); }, 800);
    };
    timer = setTimeout(() => { void poll(); }, 800);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [pendingRender, requestId, requestStatus, setCurrentRequest]);

  const run = useCallback(async <T,>(
    label: string,
    operation: (signal: AbortSignal) => Promise<T>,
    apply: (result: T) => void | Promise<void>,
    successNotice?: string,
    relatedRequestId?: string,
  ): Promise<boolean> => {
    if (busyRef.current || bootingRef.current) return false;
    const scope = scopeEpoch.current;
    const epoch = ++operationEpoch.current;
    const controller = new AbortController();
    mutationController.current = controller;
    busyRef.current = label;
    setBusy(label);
    setError(null);
    setNotice(null);
    const current = () => mounted.current && scope === scopeEpoch.current && epoch === operationEpoch.current
      && !controller.signal.aborted;
    try {
      const result = await operation(controller.signal);
      if (!current()) return false;
      await apply(result);
      if (!current()) return false;
      if (successNotice) setNotice(successNotice);
      return true;
    } catch (caught) {
      if (!current() || isAborted(caught)) return false;
      if (caught instanceof ApiError && caught.status === 409 && relatedRequestId) {
        try {
          const latest = await api.request(relatedRequestId, controller.signal);
          if (current() && requestRef.current?.id === relatedRequestId) setCurrentRequest(latest);
        } catch {
          // Keep the original conflict actionable; never retry a mutation automatically.
        }
      }
      if (current()) setError(messageOf(caught));
      return false;
    } finally {
      if (mounted.current && epoch === operationEpoch.current) {
        busyRef.current = null;
        setBusy(null);
      }
    }
  }, [setCurrentRequest]);

  const saveProfile = useCallback((input: ProfileInput) =>
    run('profile', (signal) => api.saveProfile(input, signal), setProfile, 'Профиль сохранён.'), [run]);

  const createRequest = useCallback((input: RequestInput) =>
    run('request', (signal) => api.createRequest(input, signal), setCurrentRequest), [run, setCurrentRequest]);

  const openRequest = useCallback((id: string) =>
    run('request', (signal) => api.request(id, signal), setCurrentRequest), [run, setCurrentRequest]);

  const removeProduct = useCallback((productId: string): Promise<boolean> => {
    const current = requestRef.current;
    if (!current) return Promise.resolve(false);
    return run(`remove:${productId}`, (signal) => api.removeProduct(current.id, productId, signal),
      setCurrentRequest, undefined, current.id);
  }, [run, setCurrentRequest]);

  const style = useCallback((): Promise<boolean> => {
    const current = requestRef.current;
    if (!current) return Promise.resolve(false);
    if (current.status !== 'selection') {
      setError('Дождитесь завершения поиска и отбора вещей.');
      return Promise.resolve(false);
    }
    return run('style', (signal) => api.style(current.id, signal), setCurrentRequest, undefined, current.id);
  }, [run, setCurrentRequest]);

  const replaceProduct = useCallback((outfitId: string, input: ReplacementInput): Promise<boolean> => {
    const current = requestRef.current;
    if (!current) return Promise.resolve(false);
    return run(`replace:${outfitId}`, (signal) => api.replaceProduct(current.id, outfitId, input, signal),
      applyOutfit, 'Предмет заменён. Обновляем визуализацию.', current.id);
  }, [applyOutfit, run]);

  const saveOutfit = useCallback((outfitId: string): Promise<boolean> => {
    const current = requestRef.current;
    const outfit = current?.outfits.find((item) => item.id === outfitId);
    if (!current || !outfit) return Promise.resolve(false);
    return run(`save:${outfitId}`, (signal) => api.saveOutfit(current.id, outfitId, outfit.revision, signal),
      async (saved) => { applyOutfit(saved); await refreshGallery(); }, 'Образ сохранён в галерею.', current.id);
  }, [applyOutfit, refreshGallery, run]);

  const clearError = useCallback(() => { setError(null); }, []);

  return {
    health, profile, gallery, request, booting, busy, error, notice,
    reload, saveProfile, createRequest, openRequest, removeProduct, style,
    replaceProduct, saveOutfit, refreshGallery, clearError,
  };
}
