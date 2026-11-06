import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { parseResearchObject, ResearchJsonInput } from "../ResearchJsonInput";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const example = '{"synthetic":true}';
function file(text: () => Promise<string>, size = 20) {
  const result = new File(["fixture"], "scenario.json", { type: "application/json" });
  Object.defineProperties(result, { text: { value: text }, size: { value: size } });
  return result;
}

it("loads a synthetic example only after an explicit action", () => {
  const onChange = vi.fn(), onError = vi.fn();
  render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.example" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith(example);
  expect(onError).not.toHaveBeenCalled();
});

it("accepts a bounded JSON object without calculating or saving anything", async () => {
  const onChange = vi.fn(), onError = vi.fn();
  render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  fireEvent.change(screen.getByLabelText("valuationLab.import"), { target: { files: [file(async () => '{"value":0}')] } });
  await waitFor(() => expect(onChange).toHaveBeenCalledExactlyOnceWith('{"value":0}'));
  expect(onError).not.toHaveBeenCalled();
});

it.each(["null", "[]", "broken JSON"])("rejects an invalid imported request %s", async (value) => {
  const onChange = vi.fn(), onError = vi.fn();
  render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  fireEvent.change(screen.getByLabelText("valuationLab.import"), { target: { files: [file(async () => value)] } });
  await waitFor(() => expect(onError).toHaveBeenCalledWith("valuationLab.invalidInput"));
  expect(onChange).not.toHaveBeenCalled();
});

it("rejects oversized uploads before reading their contents", () => {
  const onChange = vi.fn(), onError = vi.fn(), read = vi.fn(async () => example);
  render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  fireEvent.change(screen.getByLabelText("valuationLab.import"), { target: { files: [file(read, 64001)] } });
  expect(read).not.toHaveBeenCalled();
  expect(onError).toHaveBeenCalledExactlyOnceWith("valuationLab.invalidInput");
  expect(onChange).not.toHaveBeenCalled();
});

it("enforces the UTF-8 byte budget as well as the editor character limit", () => {
  expect(() => parseResearchObject(JSON.stringify({ text: "ệ".repeat(22000) }))).toThrow("64000 bytes");
  expect(parseResearchObject('{"amount":0,"missing":null}')).toEqual({ amount: 0, missing: null });
});

it("discards a file read that finishes after a save locks the editor", async () => {
  let resolve!: (value: string) => void;
  const onChange = vi.fn(), onError = vi.fn();
  const props = { text: example, onChange, onError, example };
  const { rerender } = render(<ResearchJsonInput {...props} />);
  fireEvent.change(screen.getByLabelText("valuationLab.import"), { target: { files: [file(() => new Promise((done) => { resolve = done; }))] } });
  rerender(<ResearchJsonInput {...props} disabled />);
  expect(screen.getByLabelText("valuationLab.input")).toBeDisabled();
  await act(async () => { resolve('{"replacement":true}'); });
  expect(onChange).not.toHaveBeenCalled();
  expect(onError).not.toHaveBeenCalled();
});

it("retains a newer file selection when an older read finishes later", async () => {
  let resolve!: (value: string) => void;
  const onChange = vi.fn(), onError = vi.fn();
  render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  const control = screen.getByLabelText("valuationLab.import");
  fireEvent.change(control, { target: { files: [file(() => new Promise((done) => { resolve = done; }))] } });
  fireEvent.change(control, { target: { files: [file(async () => '{"newer":true}')] } });
  await waitFor(() => expect(onChange).toHaveBeenCalledWith('{"newer":true}'));
  await act(async () => { resolve('{"older":true}'); });
  expect(onChange).toHaveBeenCalledTimes(1);
});

it("does not apply a file result after the component unmounts", async () => {
  let resolve!: (value: string) => void;
  const onChange = vi.fn(), onError = vi.fn();
  const { unmount } = render(<ResearchJsonInput text="" onChange={onChange} onError={onError} example={example} />);
  fireEvent.change(screen.getByLabelText("valuationLab.import"), { target: { files: [file(() => new Promise((done) => { resolve = done; }))] } });
  unmount();
  await act(async () => { resolve(example); });
  expect(onChange).not.toHaveBeenCalled();
  expect(onError).not.toHaveBeenCalled();
});
