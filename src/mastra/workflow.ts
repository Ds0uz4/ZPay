import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createStep, createWorkflow } from '@mastra/core/workflows';
import { z } from 'zod';
import { requirementsAgent, sdlcSelectionAgent, paymentProcessingAgent } from './finance-agents';
import { workspaceRoot } from './workspace';

const textFromGenerateResult = (result: any): string => {
  if (result.text) return result.text;
  if (result.object?.text) return result.object.text;
  return '';
};

const previewDir = join(workspaceRoot, 'artifacts/evaluation');

const listRequirements = createStep({
  id: 'list-requirements',
  description: 'Requirements Agent lists software requirements.',
  inputSchema: z.object({ prompt: z.string() }),
  outputSchema: z.object({ requirements: z.string() }),
  execute: async ({ inputData }) => {
    const result = await requirementsAgent.generate(inputData.prompt);
    const requirements = textFromGenerateResult(result);
    if (!requirements) throw new Error('Requirements Agent returned no text');
    return { requirements };
  },
});

const analyzePaymentProcessing = createStep({
  id: 'analyze-payment-processing',
  description: 'Payment Processing Agent analyzes payment systems in finance sector.',
  inputSchema: z.object({ prompt: z.string() }),
  outputSchema: z.object({ analysis: z.string() }),
  execute: async ({ inputData }) => {
    const result = await paymentProcessingAgent.generate(inputData.prompt);
    const analysis = textFromGenerateResult(result);
    if (!analysis) throw new Error('Payment Processing Agent returned no text');
    return { analysis };
  },
});

const selectSdlc = createStep({
  id: 'select-sdlc',
  description: 'SDLC Selection Agent chooses and justifies a lifecycle for the SRS.',
  inputSchema: z.object({ requirements: z.string() }),
  outputSchema: z.object({
    requirements: z.string(),
    sdlc: z.string(),
    document: z.string(),
  }),
  execute: async ({ inputData }) => {
    const result = await sdlcSelectionAgent.generate(
      `Select a suitable SDLC for this specification.\n\n${inputData.requirements}`,
    );
    const sdlc = textFromGenerateResult(result);
    if (!sdlc) throw new Error('SDLC Selection Agent returned no text');
    return {
      requirements: inputData.requirements,
      sdlc,
      document: `${inputData.requirements.trim()}\n\n---\n\n${sdlc.trim()}`,
    };
  },
});

const writePreview = createStep({
  id: 'write-preview',
  description: 'Write Markdown and HTML previews under artifacts/evaluation.',
  inputSchema: z.object({
    requirements: z.string(),
    sdlc: z.string(),
    document: z.string(),
  }),
  outputSchema: z.object({
    requirements: z.string(),
    sdlc: z.string(),
    document: z.string(),
    markdownPath: z.string(),
    htmlPath: z.string(),
  }),
  execute: async ({ inputData }) => {
    await mkdir(previewDir, { recursive: true });
    const markdownPath = join(previewDir, 'latest.md');
    const htmlPath = join(previewDir, 'latest.html');
    await writeFile(markdownPath, `${inputData.document.trim()}\n`, 'utf8');
    await writeFile(htmlPath, htmlPreview(inputData.document), 'utf8');
    return { ...inputData, markdownPath, htmlPath };
  },
});

const writePaymentPreview = createStep({
  id: 'write-payment-preview',
  description: 'Write Markdown and HTML previews for payment processing analysis under artifacts/evaluation.',
  inputSchema: z.object({
    analysis: z.string(),
  }),
  outputSchema: z.object({
    analysis: z.string(),
    markdownPath: z.string(),
    htmlPath: z.string(),
  }),
  execute: async ({ inputData }) => {
    await mkdir(previewDir, { recursive: true });
    const markdownPath = join(previewDir, 'payment-analysis.md');
    const htmlPath = join(previewDir, 'payment-analysis.html');
    await writeFile(markdownPath, `${inputData.analysis.trim()}\n`, 'utf8');
    await writeFile(htmlPath, htmlPreview(inputData.analysis), 'utf8');
    return { ...inputData, markdownPath, htmlPath };
  },
});

const htmlPreview = (markdown: string) => `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Requirements then SDLC</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.8.1/github-markdown.min.css"/>
  <style>body{box-sizing:border-box;min-width:200px;max-width:980px;margin:0 auto;padding:45px;}</style>
</head>
<body class="markdown-body">
  <div id="content"></div>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script>
    document.getElementById('content').innerHTML = marked.parse(${JSON.stringify(markdown)});
  </script>
</body>
</html>
`;

export const requirementsThenSdlc = createWorkflow({
  id: 'requirements-then-sdlc',
  description: 'Two-agent course flow: list requirements, then select a justified SDLC. Writes artifacts/evaluation/latest.md and latest.html.',
  inputSchema: z.object({ prompt: z.string() }),
  outputSchema: z.object({
    requirements: z.string(),
    sdlc: z.string(),
    document: z.string(),
    markdownPath: z.string(),
    htmlPath: z.string(),
  }),
})
  .then(listRequirements)
  .then(selectSdlc)
  .then(writePreview)
  .commit();

export const paymentProcessingAnalysis = createWorkflow({
  id: 'payment-processing-analysis',
  description: 'Payment Processing Agent analyzes payment systems in finance sector. Writes artifacts/evaluation/payment-analysis.md and payment-analysis.html.',
  inputSchema: z.object({ prompt: z.string() }),
  outputSchema: z.object({
    analysis: z.string(),
    markdownPath: z.string(),
    htmlPath: z.string(),
  }),
})
  .then(analyzePaymentProcessing)
  .then(writePaymentPreview)
  .commit();

export const runRequirementsThenSdlc = async (prompt: string) => {
  const run = await requirementsThenSdlc.createRun();
  const result = await run.start({ inputData: { prompt } });
  if (result.status !== 'success') {
    const message = result.status === 'failed' ? result.error.message : result.status;
    throw new Error(`Workflow failed: ${message}`);
  }
  return result.result;
};

export const runPaymentProcessingAnalysis = async (prompt: string) => {
  const run = await paymentProcessingAnalysis.createRun();
  const result = await run.start({ inputData: { prompt } });
  if (result.status !== 'success') {
    const message = result.status === 'failed' ? result.error.message : result.status;
    throw new Error(`Workflow failed: ${message}`);
  }
  return result.result;
};
