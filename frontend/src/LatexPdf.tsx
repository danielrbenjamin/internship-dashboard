import {ExternalLink, Minus, Plus} from "lucide-react";
import {useEffect, useLayoutEffect, useRef, useState, type RefObject} from "react";
import {getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy, type PDFPageProxy} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {assetHref} from "./api";
import {demoPdf} from "./demoAssets";
import {demoMode} from "./Routes";

GlobalWorkerOptions.workerSrc = workerUrl;

export type PdfPosition = {page: number; x: number; y: number};

function PdfPage({pdf, number, width, target, scroll, onSource}: {
  pdf: PDFDocumentProxy;
  number: number;
  width: number;
  target?: PdfPosition;
  scroll: RefObject<HTMLDivElement | null>;
  onSource?: (position: PdfPosition) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvasHost = useRef<HTMLDivElement>(null);
  const textHost = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [page, setPage] = useState<PDFPageProxy>();
  const [failed, setFailed] = useState(false);
  const active = visible || !!target;
  const natural = page?.getViewport({scale: 1});
  const viewport = page && natural ? page.getViewport({scale: width / natural.width}) : undefined;
  const point = target && page && viewport
    ? viewport.convertToViewportPoint(page.view[0] + target.x, page.view[3] - target.y)
    : undefined;

  useEffect(() => {
    if (!box.current) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting),
      {root: scroll.current, rootMargin: "300px"});
    observer.observe(box.current);
    return () => observer.disconnect();
  }, [scroll]);

  useEffect(() => {
    if (!active || page) return;
    let current = true;
    pdf.getPage(number).then(value => {if (current) setPage(value);})
      .catch(() => {if (current) setFailed(true);});
    return () => {current = false;};
  }, [active, number, page, pdf]);

  useEffect(() => {
    const host = canvasHost.current;
    if (!host || !page || !active) return;
    const view = page.getViewport({scale: width / page.getViewport({scale: 1}).width});
    const density = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8_000_000 / (view.width * view.height)));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.floor(view.width * density));
    canvas.height = Math.max(1, Math.floor(view.height * density));
    canvas.setAttribute("aria-label", `PDF page ${number}`);
    const render = page.render({canvas, viewport: view, transform: [density, 0, 0, density, 0, 0]});
    let current = true;
    render.promise.then(() => {if (current) host.replaceChildren(canvas);})
      .catch(() => {if (current) setFailed(true);});
    return () => {current = false; render.cancel();};
  }, [active, number, page, width]);

  useEffect(() => {
    const host = textHost.current;
    if (!host || !page || !active) return;
    const view = page.getViewport({scale: width / page.getViewport({scale: 1}).width});
    const container = document.createElement("div");
    container.className = "latex-pdf-text";
    container.style.setProperty("--total-scale-factor", String(view.scale * page.userUnit));
    const text = new TextLayer({container, textContentSource: page.streamTextContent(), viewport: view});
    let current = true;
    text.render().then(() => {if (current) host.replaceChildren(container);}).catch(() => {});
    return () => {current = false; text.cancel();};
  }, [active, page, width]);

  useLayoutEffect(() => {
    const pane = scroll.current;
    if (!pane || !target || !box.current || !page) return;
    const view = page.getViewport({scale: width / page.getViewport({scale: 1}).width});
    const [left, top] = view.convertToViewportPoint(page.view[0] + target.x, page.view[3] - target.y);
    const bounds = box.current.getBoundingClientRect();
    const origin = pane.getBoundingClientRect();
    pane.scrollTo({top: pane.scrollTop + bounds.top - origin.top + top - pane.clientHeight / 2,
      left: pane.scrollLeft + bounds.left - origin.left + left - pane.clientWidth / 2});
  }, [page, scroll, target, width]);

  return <div ref={box} className="latex-pdf-page" style={{width, height: viewport?.height ?? width * 792 / 612}}
    title={onSource ? "Double-click to jump to source" : undefined}
    onDoubleClick={event => {
      if (!viewport || !page || !onSource) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      const [x, y] = viewport.convertToPdfPoint(event.clientX - bounds.left, event.clientY - bounds.top);
      onSource({page: number, x: x - page.view[0], y: page.view[3] - y});
    }}>
    <div ref={canvasHost} className="latex-pdf-canvas"/>
    <div ref={textHost}/>
    {failed && <p role="status">Could not render this page.</p>}
    {point && <span className="latex-pdf-target" aria-hidden="true" style={{left: point[0], top: point[1]}}/>}
  </div>;
}

export function LatexPdf({url, target, onSource}: {
  url: string;
  target?: PdfPosition;
  onSource?: (position: PdfPosition) => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy>();
  const [error, setError] = useState(false);
  const [width, setWidth] = useState(0);
  const [zoom, setZoom] = useState(1);

  useLayoutEffect(() => {
    if (!scroll.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(scroll.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let current = true;
    let task: ReturnType<typeof getDocument> | undefined;
    async function load() {
      const input = demoMode ? {data: await demoPdf(url).arrayBuffer()} : {url};
      if (!current) return;
      task = getDocument({...input, useWasm: false, disableFontFace: true, useSystemFonts: true});
      const document = await task.promise;
      if (current) setPdf(document);
    }
    load().catch(() => {if (current) setError(true);});
    return () => {current = false; void task?.destroy().catch(() => {});};
  }, [url]);

  return <>
    <div className="latex-pdf-controls" role="group" aria-label="PDF preview controls">
      <button type="button" aria-label="Zoom out" title="Zoom out" disabled={zoom <= .5} onClick={() => setZoom(zoom - .25)}><Minus size={15}/></button>
      <button type="button" title="Fit to preview width" onClick={() => setZoom(1)}>{zoom === 1 ? "Fit width" : `${zoom * 100}%`}</button>
      <button type="button" aria-label="Zoom in" title="Zoom in" disabled={zoom >= 2.5} onClick={() => setZoom(zoom + .25)}><Plus size={15}/></button>
      <a href={assetHref(url)} target="_blank" rel="noreferrer" className="button" aria-label="Open PDF in a new tab" title="Open PDF in a new tab"><ExternalLink size={15}/></a>
    </div>
    <div ref={scroll} className="latex-pdf-scroll" tabIndex={0} aria-label="Compiled document">
      {error ? <p role="alert">Could not load the preview. Open the PDF in a new tab.</p>
        : !pdf ? <p role="status">Loading PDF…</p>
        : width > 0 && Array.from({length: pdf.numPages}, (_, index) =>
          <PdfPage key={index} pdf={pdf} number={index + 1} width={Math.max(40, width - 24) * zoom}
            scroll={scroll} target={target?.page === index + 1 ? target : undefined} onSource={onSource}/>)}
    </div>
  </>;
}
