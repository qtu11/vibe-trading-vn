import "@testing-library/jest-dom/vitest";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ComposerModelControls } from "../ComposerModelControls";
import { api, type LLMSettings } from "../../../lib/api";

vi.mock("../../../lib/api", () => ({ api: { listLLMModels: vi.fn(), updateLLMSettings: vi.fn() } }));
const settings: LLMSettings = { provider: "openai", model_name: "model-a", base_url: "https://api.openai.com/v1",
  api_key_configured: true, api_key_required: true, temperature: 0, timeout_seconds: 120, max_retries: 2,
  reasoning_effort: "medium", sse_timeout_seconds: 90, env_path: "agent/.env",
  providers: [{ name: "openai", label: "OpenAI", base_url_env: "OPENAI_BASE_URL", default_model: "model-a", default_base_url: "https://api.openai.com/v1", api_key_required: true, reasoning_efforts: ["low", "medium", "high"] }] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listLLMModels).mockResolvedValue({ provider: "openai", models: ["model-a", "model-b"], source: "provider" });
  vi.mocked(api.updateLLMSettings).mockImplementation(async (value: Partial<LLMSettings>) => ({ ...settings, ...value }));
});

function openPicker(overrides: Partial<LLMSettings> = {}, onChange = vi.fn()) {
  const merged = { ...settings, ...overrides };
  render(<ComposerModelControls settings={merged} disabled={false} onChange={onChange} />);
  const modelSub = (merged.model_name || "").split("/").pop() || merged.model_name;
  const trigger = screen.getByRole("button", { name: new RegExp(modelSub) });
  fireEvent.click(trigger);
  return trigger;
}

it("saves a supported slider value on release, with accessible value text", async () => {
  const changed = vi.fn();
  openPicker({}, changed);
  const slider = screen.getByRole("slider", { name: "Reasoning effort" });
  expect(slider).toHaveAttribute("aria-valuetext", "Medium");
  fireEvent.change(slider, { target: { value: "3" } });
  expect(api.updateLLMSettings).not.toHaveBeenCalled();
  fireEvent.pointerUp(slider);
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ model_name: "model-a", reasoning_effort: "high" }));
});

it("changes model and effort together through the model subpanel", async () => {
  openPicker();
  fireEvent.click(screen.getByRole("button", { name: "model-a" }));
  await screen.findByRole("option", { name: "model-b" });
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "model-b" } });
  fireEvent.change(screen.getByRole("slider"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply to next turn" }));
  await waitFor(() => expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ model_name: "model-b", reasoning_effort: "high" })));
});

it("disables the slider for an unconfirmed custom endpoint", () => {
  openPicker({ provider: "custom" });
  expect(screen.getByRole("slider")).toBeDisabled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "model-a" }));
  expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
  expect(api.listLLMModels).not.toHaveBeenCalled();
});

it("enables the slider and saves effort for a configured custom provider", async () => {
  const customProvider = {
    name: "custom",
    label: "Custom (credential vault)",
    base_url_env: "OPENAI_BASE_URL",
    default_model: "deepseek-ai/deepseek-v4.1-flash-1017",
    default_base_url: "https://api.deepseek.com",
    api_key_required: false,
    reasoning_efforts: ["low", "medium", "high"],
  };
  const changed = vi.fn();
  openPicker(
    {
      provider: "custom",
      model_name: "deepseek-ai/deepseek-v4.1-flash-1017",
      providers: [customProvider],
    },
    changed,
  );
  const slider = screen.getByRole("slider", { name: "Reasoning effort" });
  expect(slider).not.toBeDisabled();
  fireEvent.change(slider, { target: { value: "3" } });
  fireEvent.pointerUp(slider);
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(api.updateLLMSettings).toHaveBeenCalledWith(
    expect.objectContaining({
      provider: "custom",
      model_name: "deepseek-ai/deepseek-v4.1-flash-1017",
      reasoning_effort: "high",
    }),
  );
});

it("does not repeat the provider default in the closed trigger", () => {
  render(<ComposerModelControls settings={{ ...settings, reasoning_effort: "" }} disabled={false} onChange={vi.fn()} />);
  const trigger = screen.getByRole("button", { name: "model-a" });
  expect(trigger).not.toHaveTextContent(/Provider default/);
  expect(trigger).toHaveAccessibleName("model-a");
});

it("locks controls while a request is streaming", () => {
  render(<ComposerModelControls settings={settings} disabled onChange={vi.fn()} />);
  expect(screen.getByRole("button", { name: /model-a/ })).toBeDisabled();
});

it("clears unsupported efforts on a model switch before saving", async () => {
  vi.mocked(api.listLLMModels).mockResolvedValue({ provider: "openai", models: ["model-a", "model-b"], source: "provider", effort_levels: { "model-a": ["low", "high"], "model-b": [] } });
  openPicker();
  fireEvent.click(screen.getByRole("button", { name: "model-a" }));
  await screen.findByRole("option", { name: "model-b" });
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "model-b" } });
  expect(screen.getByRole("slider")).toBeDisabled();
  expect(screen.getByRole("slider")).toHaveValue("0");
  fireEvent.click(screen.getByRole("button", { name: "Apply to next turn" }));
  await waitFor(() => expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ model_name: "model-b", reasoning_effort: "" })));
});

it("resets to provider default and saves without submitting a chat", async () => {
  openPicker();
  fireEvent.click(screen.getByRole("button", { name: "Reset reasoning effort" }));
  await waitFor(() => expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: "" })));
});

it("returns focus on Escape and does not forward it to cancel generation", () => {
  const trigger = openPicker(), cancel = vi.fn();
  document.addEventListener("keydown", cancel);
  fireEvent.keyDown(screen.getByRole("slider"), { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(cancel).not.toHaveBeenCalled();
  document.removeEventListener("keydown", cancel);
});

it("does not send duplicate writes for an unchanged slider value", () => {
  openPicker();
  fireEvent.pointerUp(screen.getByRole("slider"));
  expect(api.updateLLMSettings).not.toHaveBeenCalled();
});

it("keeps an API failure visible in the popover", async () => {
  vi.mocked(api.updateLLMSettings).mockRejectedValue(new Error("Could not save settings"));
  openPicker();
  fireEvent.change(screen.getByRole("slider"), { target: { value: "3" } });
  fireEvent.pointerUp(screen.getByRole("slider"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings");
  expect(screen.getByRole("dialog")).toBeVisible();
});

it("supports keyboard release and prevents Enter from submitting the form", async () => {
  openPicker();
  const slider = screen.getByRole("slider");
  fireEvent.change(slider, { target: { value: "1" } });
  fireEvent.keyUp(slider, { key: "ArrowLeft" });
  await waitFor(() => expect(api.updateLLMSettings).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: "low" })));
  expect(fireEvent.keyDown(slider, { key: "Enter" })).toBe(false);
});
