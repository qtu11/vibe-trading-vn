import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import i18n from './src/i18n';
import './src/index.css';
import { Composer } from './src/components/chat/Composer';
import { ComposerModelControls } from './src/components/chat/ComposerModelControls';
import { ContextUsageIndicator } from './src/components/chat/ContextUsageIndicator';
import { api, type LLMSettings } from './src/lib/api';

const initial: LLMSettings = { provider:'openai', model_name:'GPT-6.1 Sol', base_url:'https://example.invalid/v1', api_key_configured:true, api_key_required:true, temperature:0, timeout_seconds:120, max_retries:2, reasoning_effort:'xhigh', sse_timeout_seconds:90, env_path:'fixture', providers:[{name:'openai', label:'OpenAI', base_url_env:'OPENAI_BASE_URL', default_model:'GPT-6.1 Sol', default_base_url:'https://example.invalid/v1', api_key_required:true, reasoning_efforts:['low','medium','high','xhigh']}] };
api.listLLMModels = async () => ({ provider:'openai', models:['GPT-6.1 Sol','Alternative model with a deliberately very long display name'], source:'provider', effort_levels:{'GPT-6.1 Sol':['low','medium','high','xhigh'],'Alternative model with a deliberately very long display name':[]} });
api.updateLLMSettings = async (value) => ({...initial,...value});
const localFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = String(input);
  if (url.startsWith('/settings/llm/context')) return new Response(JSON.stringify({model:'GPT-6.1 Sol',window:128000,source:'provider_reported',confidence:'provider_reported',compact_at:92000,prompt_cost_cap:100000,automatic_compaction:true}), {headers:{'Content-Type':'application/json'}});
  return localFetch(input,init);
};
await i18n.changeLanguage('vi');
const params = new URLSearchParams(location.search);
document.documentElement.classList.toggle('dark', params.get('theme') !== 'light');
const noop = () => {};
function Review() {
  const [settings,setSettings] = useState<LLMSettings>(params.has('custom') ? {...initial,provider:'custom',model_name:'deepseek-ai/deepseek-v4.1-flash-1017',reasoning_effort:''} : initial);
  const controls = <><ContextUsageIndicator sessionId={null} compact modelKey={`${settings.provider}:${settings.model_name}`} /><ComposerModelControls settings={settings} disabled={params.has('streaming')} onChange={setSettings} /></>;
  return <main className="flex h-dvh min-w-0 bg-background text-foreground">
    <aside className="w-12 shrink-0 border-r" aria-hidden="true" />
    <section className="flex min-w-0 flex-1 flex-col">
      <div className="flex-1 p-5 text-xs text-muted-foreground">Kiểm tra giao diện · dữ liệu mô phỏng · không gọi provider</div>
      <div className="px-4 pt-3 pb-5"><div className="mx-auto max-w-3xl">
        <Composer streaming={params.has('streaming')} hasCompletedTurn={false} showExport={false} canExport={false} goalComposerActive={false} swarmPreset={null} onSubmit={noop} onCancel={noop} onExport={noop} onStartGoal={noop} onCancelGoal={noop} onStartSwarm={noop} onCancelSwarm={noop} controls={controls} />
      </div></div>
    </section>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Review />);
