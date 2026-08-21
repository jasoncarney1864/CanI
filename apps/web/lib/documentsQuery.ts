// Pure query-string builder for GET /api/documents (docs/21 §1.9), split out from
// DocumentsView so the filter/sort/pagination -> query-param mapping is unit-testable
// without rendering the component.

import type { DocumentStatus } from "./types";

export const DOCUMENTS_PAGE_SIZE = 50;

export type DocumentsSortField = "created_at" | "updated_at" | "title";
export type DocumentsSortOrder = "asc" | "desc";

export interface DocumentsListQuery {
  spoke: string;
  q: string;
  statusFilter: DocumentStatus | "all";
  sort: DocumentsSortField;
  order: DocumentsSortOrder;
  page: number;
  pageSize?: number;
}

/** Builds the query string docs-api's GET /documents expects (docs/21 §1.2). Trims `q`
 * and omits it entirely when blank rather than sending an empty substring filter. */
export function buildDocumentsListQuery(params: DocumentsListQuery): string {
  const pageSize = params.pageSize ?? DOCUMENTS_PAGE_SIZE;
  const sp = new URLSearchParams();
  sp.set("spoke", params.spoke);
  const trimmedQ = params.q.trim();
  if (trimmedQ) sp.set("q", trimmedQ);
  if (params.statusFilter !== "all") sp.set("status", params.statusFilter);
  sp.set("sort", params.sort);
  sp.set("order", params.order);
  sp.set("limit", String(pageSize));
  sp.set("offset", String(params.page * pageSize));
  return sp.toString();
}
