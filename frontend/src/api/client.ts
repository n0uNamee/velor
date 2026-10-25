import type {
  Gallery,
  Health,
  ImageKind,
  ImageRef,
  Outfit,
  Profile,
  ProfileInput,
  ReplacementInput,
  RequestInput,
  RequestState,
} from '../types';

/** Never contains an auth header or the Telegram initData. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

interface ApiOptions {
  signal?: AbortSignal;
  body?: object | FormData;
  public?: boolean;
}

const statusMessages: Record<number, string> = {
  400: 'Проверьте данные и попробуйте ещё раз.',
  401: 'Откройте VÉLOR через Telegram, чтобы продолжить.',
  403: 'Нет доступа к этому действию.',
  404: 'Данные больше не доступны. Обновите страницу.',
  409: 'Образ уже изменился. Получаем актуальную версию.',
  413: 'Фотография слишком большая. Выберите файл меньшего размера.',
  415: 'Этот формат изображения не поддерживается.',
  422: 'Проверьте заполненные поля или формат фотографии.',
  429: 'Слишком много запросов. Попробуйте чуть позже.',
  502: 'Сервис временно недоступен. Попробуйте ещё раз.',
  503: 'Сервис пока недоступен. Проверьте подключение backend.',
};

/** The Telegram signed payload stays in memory and is sent only to our API. */
function authHeaders(publicEndpoint = false): Headers {
  const headers = new Headers({ Accept: 'application/json' });
  const initData = typeof window === 'undefined' ? '' : window.Telegram?.WebApp?.initData;
  if (initData) {
    headers.set('Authorization', `tma ${initData}`);
  } else if (import.meta.env.DEV) {
    headers.set('X-Dev-User', 'demo');
  } else if (!publicEndpoint) {
    throw new ApiError(401, statusMessages[401]);
  }
  return headers;
}

async function send(path: string, method: string, options: ApiOptions = {}): Promise<Response> {
  const headers = authHeaders(options.public);
  const multipart = options.body instanceof FormData;
  if (options.body && !multipart) headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      signal: options.signal,
      body: options.body ? (multipart ? options.body as FormData : JSON.stringify(options.body)) : undefined,
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    if (options.signal?.aborted) throw error;
    throw new ApiError(0, 'Не удалось связаться с сервером. Проверьте подключение и попробуйте снова.');
  }

  // Error bodies may echo user input. Use controlled messages and never log them.
  if (!response.ok) {
    const message = statusMessages[response.status] ??
      (response.status >= 500 ? 'Ошибка сервера. Попробуйте ещё раз.' : 'Не удалось выполнить действие.');
    throw new ApiError(response.status, message);
  }
  return response;
}

async function call<T>(path: string, method: string, options: ApiOptions = {}): Promise<T> {
  const response = await send(path, method, options);
  try {
    return await response.json() as T;
  } catch {
    throw new ApiError(502, 'Сервер вернул некорректный ответ. Попробуйте ещё раз.');
  }
}

const id = (value: string) => encodeURIComponent(value);

/** One same-origin adapter; there is deliberately no automatic fixture fallback. */
export const api = {
  health: (signal?: AbortSignal) => call<Health>('/health', 'GET', { signal, public: true }),
  profile: (signal?: AbortSignal) => call<Profile | null>('/profile', 'GET', { signal }),
  saveProfile: (input: ProfileInput, signal?: AbortSignal) =>
    call<Profile>('/profile', 'PUT', { body: { style_text: input.style_text, images: input.images ?? [] }, signal }),
  upload: (file: File, kind: ImageKind, signal?: AbortSignal) => {
    if (!file.size || !file.type.startsWith('image/')) {
      return Promise.reject(new ApiError(415, 'Выберите непустой файл изображения.'));
    }
    const body = new FormData();
    body.append('file', file);
    body.append('kind', kind);
    return call<ImageRef>('/uploads', 'POST', { body, signal });
  },
  imageBlob: async (imageId: string, signal?: AbortSignal): Promise<Blob> => {
    const response = await send(`/uploads/${id(imageId)}`, 'GET', { signal });
    const blob = await response.blob();
    if (!blob.type.startsWith('image/')) throw new ApiError(415, 'Сервер не вернул изображение.');
    return blob;
  },
  createRequest: (input: RequestInput, signal?: AbortSignal) =>
    call<RequestState>('/requests', 'POST', { body: { ...input, images: input.images ?? [] }, signal }),
  request: (requestId: string, signal?: AbortSignal) =>
    call<RequestState>(`/requests/${id(requestId)}`, 'GET', { signal }),
  removeProduct: (requestId: string, productId: string, signal?: AbortSignal) =>
    call<RequestState>(`/requests/${id(requestId)}/products/${id(productId)}`, 'DELETE', { signal }),
  style: (requestId: string, signal?: AbortSignal) =>
    call<RequestState>(`/requests/${id(requestId)}/style`, 'POST', { body: {}, signal }),
  replaceProduct: (requestId: string, outfitId: string, input: ReplacementInput, signal?: AbortSignal) =>
    call<Outfit>(`/requests/${id(requestId)}/outfits/${id(outfitId)}`, 'PATCH', { body: input, signal }),
  saveOutfit: (requestId: string, outfitId: string, expectedRevision: number, signal?: AbortSignal) =>
    call<Outfit>(`/requests/${id(requestId)}/outfits/${id(outfitId)}/save`, 'POST', {
      body: { expected_revision: expectedRevision }, signal,
    }),
  gallery: (signal?: AbortSignal) => call<Gallery>('/gallery', 'GET', { signal }),
};
