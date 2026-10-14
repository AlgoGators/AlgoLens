import { DeskApi, DeskApiError } from '../../infrastructure/api/deskApi';
import type { ApprovalPage, ApproveResult, CommandResult } from '../../infrastructure/api/deskApi';

export { DeskApiError };
export type { ApprovalPage, ApproveResult, CommandResult };

/** The QT desk use cases as the components see them. */
export const DeskService = DeskApi;
