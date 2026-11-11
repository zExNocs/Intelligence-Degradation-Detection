import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

const CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";

/** Keep model HTML in a non-origin-preserving frame with restrictive policy. */
export function HtmlPreview({ html, large = false }: { html: string; large?: boolean }) {
  const [url, setUrl] = useState('');
  const policy = useQuery({
    queryKey: ['preview-policy'],
    queryFn: () => api<{ nonce: string }>('/preview-policy'),
    staleTime: Infinity,
  });
  const document = useMemo(() => {
    const source = html.trim().replace(/^```(?:html)?\s*\n([\s\S]*?)\n```$/i, '$1');
    // Never parse model markup in the host document: even inert parsing can load resources.
    const authorized = source.replace(/<script\b/gi, `<script nonce="${policy.data?.nonce ?? ''}"`);
    return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${CSP}"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${authorized}</body></html>`;
  }, [html, policy.data]);
  useEffect(() => {
    if (!policy.data) return;
    const value = URL.createObjectURL(new Blob([document], { type: 'text/html' }));
    setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [document, policy.data]);
  return (
    <div className={large ? 'preview-large' : 'preview-small'}>
      {url && (
        <iframe
          title="Isolated HTML preview"
          src={url}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          loading="lazy"
          tabIndex={large ? 0 : -1}
        />
      )}
    </div>
  );
}
