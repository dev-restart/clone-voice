<script lang="ts">
  import AudioDownload from './AudioDownload.svelte';
  import { Button } from '$lib/components/ui/button';
  import { t } from '$lib/i18n/index.svelte';
  import { audioUrl, formatDate, formatTime } from '$lib/studio/api';
  import type { SoundEffectResult } from '$lib/studio/types';

  let { results, title, saving = false, onReuse, onSimilar, onRemove }: {
    results: SoundEffectResult[];
    title: string;
    saving?: boolean;
    onReuse?: (result: SoundEffectResult) => void;
    onSimilar?: (result: SoundEffectResult) => void;
    onRemove?: (id: string) => void;
  } = $props();

  function downloadName(result: SoundEffectResult) {
    return `${title}-${result.id.slice(0, 8)}`;
  }
</script>

<div class="grid min-w-0 gap-3.5 min-[1400px]:grid-cols-2">
  {#each [...results].reverse() as result, index (result.id)}
    {@const version = results.length - index}
    <article class="border-border bg-card min-w-0 rounded-xl border p-5">
      <div class="mb-3.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <strong class="text-sm">{t('soundresult.version', { n: version })}</strong>
        <span class="text-muted-foreground text-xs">{formatTime(result.duration_seconds)} · {formatDate(result.created_at)}</span>
      </div>
      <audio class="block h-10 w-full min-w-0" controls preload="none" src={audioUrl(result.audio_url)} aria-label={t('soundresult.listen', { title, n: version })}></audio>
      <p class="text-muted-foreground mt-3.5 line-clamp-2 text-xs break-words">{result.prompt}</p>
      <details class="border-border-soft mt-3 border-t pt-2.5">
        <summary class="text-muted-foreground hover:text-foreground cursor-pointer text-xs">{t('soundresult.showPrompt')}</summary>
        <p class="text-muted-foreground mt-2.5 text-xs break-words whitespace-pre-wrap">{result.prompt}</p>
        {#if result.generation_prompt && result.generation_prompt !== result.prompt}
          <strong class="text-subtle-foreground mt-3 block text-[11px]">{t('soundresult.generationPrompt')}</strong>
          <p class="text-muted-foreground mt-1 text-xs break-words whitespace-pre-wrap">{result.generation_prompt}</p>
        {/if}
        {#if result.negative_prompt}
          <strong class="text-subtle-foreground mt-3 block text-[11px]">{t('soundresult.negative')}</strong>
          <p class="text-muted-foreground mt-1 text-xs break-words whitespace-pre-wrap">{result.negative_prompt}</p>
        {/if}
        <small class="text-subtle-foreground mt-3 block text-[10px]">{t('soundresult.seed', { seed: result.seed })} · {result.model_id}</small>
      </details>
      <div class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1">
        <AudioDownload path={result.audio_url} filename={downloadName(result)} label={t('soundresult.downloadLabel', { title, n: version })} />
        {#if onReuse}<Button variant="ghost" size="sm" disabled={saving} onclick={() => onReuse?.(result)}>{t('soundresult.reuse')}</Button>{/if}
        {#if onSimilar}<Button variant="ghost" size="sm" disabled={saving} onclick={() => onSimilar?.(result)}>{t('soundresult.similar')}</Button>{/if}
        {#if onRemove}<Button variant="ghost" size="sm" class="text-danger" disabled={saving} onclick={() => onRemove?.(result.id)}>{t('soundresult.remove')}</Button>{/if}
      </div>
    </article>
  {/each}
</div>

<style>
  details > summary { list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
</style>
