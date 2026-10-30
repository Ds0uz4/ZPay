import { mastra } from './src/mastra/index.js';
async function test() {
  const store = await mastra.getStorage()?.getStore('observability');
  const traces = await store?.listTraces();
  console.log('Traces count:', traces?.length);
  console.log('Traces:', JSON.stringify(traces, null, 2));
}
test().catch(console.error);
