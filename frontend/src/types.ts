/** HTTP API v1. Keep wire names in snake_case; see CONTRACTS.md. */
export type Category = 'headwear' | 'tops' | 'bottoms' | 'shoes' | 'accessories';
export type ImageKind = 'wardrobe' | 'reference';
export type RuntimeMode = 'demo' | 'live';

export interface ImageRef {
  id: string;
  kind: ImageKind;
  url: string | null;
  local_path: string | null;
  mime_type: string | null;
}

export interface Profile {
  id: string;
  style_text: string;
  images: ImageRef[];
  created_at: string;
  updated_at: string;
}

export interface Constraint {
  text: string;
  strength: 'hard' | 'soft';
  provenance: 'profile' | 'request' | 'inferred';
  confidence: number;
}

export interface StyleBrief {
  schema_version: '1.0';
  id: string;
  profile_id: string;
  original_profile_text: string;
  original_request_text: string;
  images: ImageRef[];
  categories: Category[];
  search_queries: string[];
  constraints: Constraint[];
  preferences: Constraint[];
  exclusions: Constraint[];
  budget_rub: number | null;
  sizes: Record<string, string> | null;
  city: string | null;
  unknowns: string[];
  mode: RuntimeMode;
}

export interface Product {
  id: string;
  title: string;
  category: Category;
  source_id: string;
  source_url: string;
  image_url: string | null;
  price_rub: number | null;
  price_note: string | null;
  sizes: string[];
  availability: 'in_stock' | 'out_of_stock' | 'unknown';
  verified_at: string | null;
  verification: 'verified' | 'unverified' | 'demo';
  evidence: string[];
  is_demo: boolean;
}

export type SourceState =
  | 'queued'
  | 'searching'
  | 'verifying'
  | 'complete'
  | 'inaccessible'
  | 'unconfigured'
  | 'failed';

export interface SourceStatus {
  source_id: string;
  name: string;
  state: SourceState;
  found: number;
  detail: string | null;
}

export interface ProductCatalog {
  schema_version: '1.0';
  products: Product[];
  sources: SourceStatus[];
  warnings: string[];
}

export interface Outfit {
  id: string;
  request_id: string;
  title: string;
  product_ids: string[];
  revision: number;
  render_revision: number | null;
  render_status: 'pending' | 'ready' | 'failed';
  render_url: string | null;
  saved: boolean;
  explanation: string;
  render_disclaimer: string;
}

export interface RequestState {
  id: string;
  profile_id: string;
  text: string;
  status: 'searching' | 'selection' | 'styling' | 'ready' | 'failed';
  brief: StyleBrief;
  catalog: ProductCatalog;
  excluded_product_ids: string[];
  outfits: Outfit[];
  created_at: string;
  error: string | null;
}

export interface Gallery {
  outfits: Outfit[];
  products: Product[];
}

export interface Health {
  status: string;
  mode: RuntimeMode;
  environment: string;
  auth_status?: 'locked' | 'telegram' | 'local_dev' | 'web';
  providers: {
    brief: string | boolean | null;
    search: string | boolean | null;
    render: string | boolean | null;
  };
  search_workers: number;
  catalog_source?: string;
}

export interface WebSession {
  authenticated: boolean;
  csrf_token?: string;
}

export interface ProfileInput {
  style_text: string;
  images?: ImageRef[];
}

export interface RequestInput {
  text: string;
  images?: ImageRef[];
  budget_rub?: number | null;
  sizes?: Record<string, string> | null;
  city?: string | null;
}

export interface ReplacementInput {
  old_product_id: string;
  new_product_id: string;
  expected_revision: number;
}

export interface TelegramWebApp {
  initData?: string;
  ready?: () => void;
  expand?: () => void;
  close?: () => void;
  colorScheme?: 'light' | 'dark';
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}
