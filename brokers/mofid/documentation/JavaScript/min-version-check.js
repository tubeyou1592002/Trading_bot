(async function checkMinimumVersion() {
	const versionFileFetch = await fetch('./app-version.json');
	if (!versionFileFetch.ok) {
		return undefined;
	}
	const environment = await versionFileFetch.json();
	const apiPath = environment.apiPath;
	const currentVersion = environment.currentVersion;
	if (currentVersion === '${VERSION}') {
		return undefined;
	}
	if (!apiPath) {
		console.warn('API path for version check is not defined.');
		return undefined;
	}
	const res = await fetch(apiPath);
	const response = res.ok ? await res.json() : undefined;
	const appHasUnstableVersion =
		currentVersion &&
		(((response || {}).obsoleteBuildNumbers || '').includes(currentVersion) ||
			Number(currentVersion) < (Number((response || {}).minimumRequiredVersion || 1) || 1));
	if (appHasUnstableVersion && 'serviceWorker' in navigator) {
		// Clear all cache storage
		if ('caches' in window) {
			const cacheNames = await caches.keys();
			for (const cacheName of cacheNames) {
				await caches.delete(cacheName);
			}
		}
		// Unregister all service workers
		const registrations = await navigator.serviceWorker.getRegistrations();
		for (const registration of registrations) {
			await registration.unregister();
		}
		window.location.reload();
	}
})();
