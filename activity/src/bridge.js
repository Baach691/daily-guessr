import { DiscordSDK } from '@discord/embedded-app-sdk';

const CLIENT_ID = import.meta.env.VITE_DISCORD_CLIENT_ID;
const sdk = CLIENT_ID ? new DiscordSDK(CLIENT_ID) : null;
const sdkReady = sdk
  ? sdk.ready()
  : Promise.reject(new Error('VITE_DISCORD_CLIENT_ID absent'));

async function openOutsideActivity(link) {
  const url = new URL(link.href, window.location.href).href;
  link.setAttribute('aria-busy', 'true');

  try {
    await sdkReady;
    const result = await sdk.commands.openExternalLink({ url });
    if (result?.opened) return;
    throw new Error('Discord a refusé le lien externe');
  } catch (error) {
    console.warn('Ouverture via Discord impossible, utilisation du navigateur', error);
    const popup = window.open(url, '_blank', 'noopener,noreferrer');
    if (!popup) window.location.assign(url);
  } finally {
    link.removeAttribute('aria-busy');
  }
}

document.addEventListener('click', (event) => {
  const link = event.target.closest('[data-activity-external]');
  if (!link) return;
  event.preventDefault();
  openOutsideActivity(link);
});
