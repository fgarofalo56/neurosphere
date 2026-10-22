/**
 * Compile a validated Vega-Lite subset to Vega and run it with the CSP-safe interpreter.
 * No expression is ever compiled to JavaScript: Vega parses with `ast: true` and the View is
 * given `expressionInterpreter`. The loader refuses everything, so no url data can load.
 */
import { expressionInterpreter } from "vega-interpreter";
import { compile, type TopLevelSpec } from "vega-lite";
import { parse, View, type Loader } from "vega";
import { specViolations } from "../protocol";

const denyLoader: Loader = {
  load: () => Promise.reject(new Error("loading is disabled")),
  sanitize: () => Promise.reject(new Error("loading is disabled")),
  http: () => Promise.reject(new Error("loading is disabled")),
  file: () => Promise.reject(new Error("loading is disabled")),
};

export class InvalidSpecError extends Error {}

/** Renders `spec` into `container`; resolves to the running View so callers can finalize it. */
export async function renderSpec(spec: unknown, container: HTMLElement): Promise<View> {
  if (specViolations(spec).length > 0) throw new InvalidSpecError("spec rejected");
  const vega = compile(spec as TopLevelSpec).spec;
  const runtime = parse(vega, undefined, { ast: true });
  const view = new View(runtime, {
    expr: expressionInterpreter,
    loader: denyLoader,
    renderer: "svg",
    container,
    hover: false,
  } as ConstructorParameters<typeof View>[1]);
  await view.runAsync();
  return view;
}
