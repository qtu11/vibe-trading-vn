import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ComposerModelControls } from "../ComposerModelControls";
import { api, type LLMSettings } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { listLLMModels: vi.fn(), updateLLMSettings: vi.fn() } }));
const settings: LLMSettings = { provider: "openai", model_name: "model-a", base_url: "https://api.openai.com/v1",
  api_key_configured: true, api_key_required: true, temperature: 0, timeout_seconds: 120, max_retries: 2,
  reasoning_effort: "medium", sse_timeout_seconds: 90, env_path: "agent/.env",
  providers: [{ name: "openai", label: "OpenAI", base_url_env: "OPENAI_BASE_URL", default_model: "model-a", default_base_url: "https://api.openai.com/v1", api_key_required: true, reasoning_efforts: ["low","medium","high"] }] };

beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.listLLMModels).mockResolvedValue({ provider:"openai", models:["model-a","model-b"],source:"provider" }); });

it("applies model and effort together to the real settings API", async () => {
  const changed = vi.fn();
  vi.mocked(api.updateLLMSettings).mockResolvedValue({ ...settings, model_name: "model-b", reasoning_effort: "high" });
  render(<ComposerModelControls settings={settings} disabled={false} onChange={changed} />);
  fireEvent.click(screen.getByRole("button", { name:/model-a/ }));
  await screen.findByRole("option", { name:"model-b" });
  fireEvent.change(screen.getByRole("combobox", {name:"Model"}), {target:{value:"model-b"}});
  fireEvent.change(screen.getByRole("combobox", {name:"Reasoning effort"}), {target:{value:"high"}});
  fireEvent.click(screen.getByRole("button", {name:"Apply to next turn"}));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({model_name:"model-b",reasoning_effort:"high",provider:"openai"}));
});

it("does not offer a working effort control for an unconfirmed custom endpoint", () => {
  render(<ComposerModelControls settings={{...settings,provider:"custom"}} disabled={false} onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", {name:/model-a/}));
  expect(screen.getByRole("combobox", {name:"Reasoning effort"})).toBeDisabled();
  expect(screen.getByRole("combobox", {name:"Model"})).toBeDisabled();
  expect(api.listLLMModels).not.toHaveBeenCalled();
});

it("locks controls while a request is streaming", () => {
  render(<ComposerModelControls settings={settings} disabled onChange={vi.fn()} />);
  expect(screen.getByRole("button", {name:/model-a/})).toBeDisabled();
});

it("uses per-model adapter support and clears dormant efforts before saving", async () => {
  vi.mocked(api.listLLMModels).mockResolvedValue({ provider:"openai", models:["model-a","model-b"], source:"provider", effort_levels: { "model-a": ["low", "high"], "model-b": [] } });
  vi.mocked(api.updateLLMSettings).mockResolvedValue({ ...settings, model_name:"model-b", reasoning_effort:"" });
  render(<ComposerModelControls settings={settings} disabled={false} onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name:/model-a/ }));
  await screen.findByRole("option", { name:"model-b" });
  expect(screen.queryByRole("option", { name:"Medium" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name:"Reasoning effort" }), { target:{ value:"high" } });
  fireEvent.change(screen.getByRole("combobox", { name:"Model" }), { target:{ value:"model-b" } });
  expect(screen.getByRole("combobox", { name:"Reasoning effort" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name:"Reasoning effort" })).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name:"Apply to next turn" }));
  await waitFor(() => expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ model_name:"model-b", reasoning_effort:"" })));
});

it("returns focus when the model picker close button is used", () => {
  render(<ComposerModelControls settings={settings} disabled={false} onChange={vi.fn()} />);
  const trigger = screen.getByRole("button", { name:/model-a/ });
  fireEvent.click(trigger); fireEvent.click(screen.getByRole("button", { name:"Close" }));
  expect(trigger).toHaveFocus();
});
