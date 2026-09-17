// Gathers IRIS-specific metrics from this project's own already-documented
// SysAdmin REST API (docs/api-matrix.md) and hands them to the Embedded
// Python HealthAnalyzer (js/api/health-api.js) for scoring. This is the
// bridge between "data this app already knows how to fetch" and "analysis
// only Embedded Python can add" (real CPU/memory via psutil) — see
// docs/health-analyzer.md for the full design rationale.
//
// Deliberately does NOT populate shared_memory_used_pages/allocated_pages:
// Phase 3 established (docs/api-matrix.md section 13) that the shared-memory
// endpoint's "Total" row sums three different pools and has no valid single
// capacity figure to divide against — resurrecting that computation here
// would reintroduce the same misleading percentage this project already
// caught and removed from the dashboard. The analyzer still accepts the
// field for when/if a real capacity figure becomes available.

import * as monitorApi from '../api/monitor-api.js';
import * as taskApi from '../api/task-api.js';
import * as databaseApi from '../api/database-api.js';
import { analyzeHealth } from '../api/health-api.js';

const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;

async function gatherIrisMetrics() {
  const [mainResult, historyResult, dirsResult] = await Promise.allSettled([
    monitorApi.getMainDashboard(),
    taskApi.getTaskHistory({ maxRows: 200 }),
    databaseApi.listDatabaseDirs({ maxRows: 500 }),
  ]);

  const metrics = {};

  if (mainResult.status === 'fulfilled') {
    const main = mainResult.value;
    if (main.Licensing) {
      metrics.license_used = main.Licensing.LicenseUse;
      metrics.license_limit = main.Licensing.LicenseLimit;
    }
    if (main.SystemUsage) {
      metrics.active_processes = main.SystemUsage.Processes;
      metrics.csp_sessions = main.SystemUsage.CSPSessions;
    }
    if (main.Alerts) {
      metrics.serious_audit_alerts = main.Alerts.SeriousAlerts;
    }
  }

  if (historyResult.status === 'fulfilled') {
    const cutoff = Date.now() - TWENTY_FOUR_HOURS_MS;
    const recentFailures = (historyResult.value || []).filter((entry) => {
      if (!entry.ErrNumber) return false;
      // LogDatetime has no timezone marker; treated as UTC, which matches
      // this project's Docker-based dev/demo setup but may drift on a
      // server configured in a different timezone. Acceptable for a
      // best-effort "recent failures" count, not a precise cutoff.
      const logged = Date.parse(entry.LogDatetime?.replace(' ', 'T') + 'Z');
      return !Number.isNaN(logged) && logged >= cutoff;
    });
    metrics.failed_tasks_24h = recentFailures.length;
  }

  if (dirsResult.status === 'fulfilled') {
    metrics.databases_near_full = (dirsResult.value || [])
      .filter((dir) => typeof dir.MaxSize === 'number' && dir.MaxSize > 0 && dir.Size / dir.MaxSize > 0.9)
      .map((dir) => dir.Directory);
  }

  return metrics;
}

/**
 * Gathers IRIS metrics from the app's own REST API and runs the Embedded
 * Python HealthAnalyzer over them. Returns null if the user cancels the
 * one-time Basic-auth prompt (see js/services/mgmnt-auth.js) rather than
 * throwing — callers should treat that as "not run", not an error.
 */
export async function runHealthAnalysis() {
  const irisMetrics = await gatherIrisMetrics();
  return analyzeHealth(irisMetrics);
}
