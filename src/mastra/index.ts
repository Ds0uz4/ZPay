import { Mastra } from '@mastra/core/mastra';
import { LibSQLStore } from '@mastra/libsql';
import { architectAgent } from './architect-agent';
import { requirementsAgent, sdlcSelectionAgent, paymentProcessingAgent } from './finance-agents';
import { assertCorpusSearchable } from './rag';
import { requirementsThenSdlc, paymentProcessingAnalysis } from './workflow';
import { architectWorkspace } from './workspace';

export const mastra = new Mastra({
  agents: { architectAgent, requirementsAgent, sdlcSelectionAgent, paymentProcessingAgent },
  workflows: { requirementsThenSdlc, paymentProcessingAnalysis },
  storage: new LibSQLStore({
    id: 'architect-storage',
    url: process.env.MASTRA_DATABASE_URL ?? 'file:./architect.db',
  }),
  workspace: architectWorkspace,
});

await architectWorkspace.init();
await assertCorpusSearchable();
