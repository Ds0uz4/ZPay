import { Mastra } from '@mastra/core/mastra';
import { createLogger } from '@mastra/core/logger';
import { MastraCompositeStore } from '@mastra/core/storage';
import { LibSQLStore } from '@mastra/libsql';
import { DuckDBStore } from '@mastra/duckdb';
import { Observability, MastraStorageExporter } from '@mastra/observability';
import { architectAgent } from './architect-agent';
import { requirementsAgent, sdlcSelectionAgent, paymentProcessingAgent } from './finance-agents';
import { assertCorpusSearchable } from './rag';
import { requirementsThenSdlc, paymentProcessingAnalysis } from './workflow';
import { architectWorkspace } from './workspace';

export const mastra = new Mastra({
  logger: createLogger({
    name: 'Mastra',
    level: 'debug',
  }),
  agents: { architectAgent, requirementsAgent, sdlcSelectionAgent, paymentProcessingAgent },
  workflows: { requirementsThenSdlc, paymentProcessingAnalysis },
  storage: new MastraCompositeStore({
    id: 'architect-storage',
    default: new LibSQLStore({
      id: 'architect-libsql',
      url: process.env.MASTRA_DATABASE_URL ?? 'file:./architect.db',
    }),
    domains: {
      observability: new DuckDBStore({
        path: process.env.MASTRA_OBSERVABILITY_DB_PATH ?? './observability.duckdb',
      }).observability,
    },
  }),
  observability: new Observability({
    configs: {
      default: {
        serviceName: 'architect-app',
        exporters: [new MastraStorageExporter()],
      },
    },
  }),
  workspace: architectWorkspace,
  workers: false,
});

await architectWorkspace.init();
await assertCorpusSearchable();
