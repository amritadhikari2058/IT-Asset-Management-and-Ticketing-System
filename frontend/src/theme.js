// Single source of truth for the palette (mirrors backend config.settings.THEME,
// extended with semantic tokens; CSS variables in index.css carry the same values).
export const THEME = {
  primary: '#1D4ED8',
  primaryHover: '#1B42B8',
  accent: '#1D4ED8',
  mainBackground: '#FFFFFF',
  supportingBackground: '#F8FAFC',
  mainText: '#1E293B',
  borders: '#E2E8F0',
  // Semantic extensions (see :root in index.css).
  mutedText: '#475569',
  success: '#15803D',
  successBg: '#F0FDF4',
  successBorder: '#BBF7D0',
  danger: '#B91C1C',
  dangerBg: '#FEF2F2',
  dangerBorder: '#FECACA',
  warning: '#B45309',
  warningBg: '#FFFBEB',
  warningBorder: '#FDE68A',
  info: '#1E40AF',
  infoBg: '#EFF6FF',
  infoBorder: '#BFDBFE',
  // Extended semantic tokens for data visualization
  infoActive: '#2563EB',
  infoHover: '#1D4ED8',
  // Status tones for dashboard KPI badges
  kpiSuccess: '#14b8a6',
  kpiWarning: '#f59e0b',
  kpiDanger: '#ef4444',
  kpiMuted: '#64748B',
};
