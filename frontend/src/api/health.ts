import type { ConfigStatus, DashboardStats, HealthResponse } from '../types/api';
import { apiRequest } from './client';

export const getHealth = () => apiRequest<HealthResponse>('/health');
export const getConfig = () => apiRequest<ConfigStatus>('/config');
export const getStats = () => apiRequest<DashboardStats>('/stats');
