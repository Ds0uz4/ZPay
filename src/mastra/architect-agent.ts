import { Agent } from '@mastra/core/agent';
import { chatModel } from './lm-studio';

export const architectAgent = new Agent({
  id: 'architect-agent',
  name: 'ZPay Coordinator',
  description: 'General architecture agent for finance scenarios.',
  instructions: 'Provide architectural guidance for finance systems, focusing on requirements, security, compliance, and system design.',
  model: chatModel,
  defaultOptions: {
    modelSettings: { maxOutputTokens: 200 },
    providerOptions: { lmStudio: { reasoningEffort: 'none', enable_thinking: false } },
  },
});
