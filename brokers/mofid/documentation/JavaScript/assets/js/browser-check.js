/**
 * Browser version compatibility checker
 * Checks if the user's browser meets the minimum version requirements
 * and displays appropriate warnings if needed
 */

// SVG icon for the warning alert
const iconAlertSVG =
	'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="36" height="36" viewBox="0 0 24 24"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 0.87793C12.3069 0.87793 12.6962 0.911609 13.0241 1.0307C13.7791 1.30489 14.1225 1.7131 14.5027 2.16498L14.5326 2.20051C15.6287 3.50221 17.1301 5.52401 18.8638 8.49604C21.001 12.1599 22.0535 15.2888 22.5574 17.2397L22.5658 17.2722C22.6183 17.4752 22.6807 17.7162 22.705 17.9698C22.7334 18.2669 22.7093 18.5485 22.6388 18.8651C22.571 19.1697 22.4068 19.4939 22.2702 19.7251C22.1337 19.9564 21.9291 20.2568 21.6951 20.4632C21.4621 20.6687 21.2385 20.8247 20.978 20.942C20.7521 21.0437 20.5262 21.1015 20.3486 21.1469L20.3486 21.1469L20.3188 21.1546C18.6852 21.5737 16.033 21.9999 12 21.9999C7.96696 21.9999 5.31484 21.5737 3.68119 21.1546L3.65143 21.1469C3.47377 21.1015 3.24787 21.0437 3.02198 20.942C2.76146 20.8247 2.53785 20.6687 2.3049 20.4632C2.07091 20.2568 1.86634 19.9564 1.72976 19.7251C1.59318 19.4939 1.42895 19.1697 1.36117 18.8651C1.29072 18.5485 1.26655 18.2669 1.29498 17.9698C1.31926 17.7162 1.38164 17.4752 1.43421 17.2722L1.44261 17.2397C1.94651 15.2888 2.99896 12.1599 5.13622 8.49604C6.86989 5.52401 8.37131 3.50221 9.46744 2.20051L9.49733 2.16498C9.8775 1.7131 10.2209 1.30489 10.9759 1.0307C11.3038 0.911609 11.6931 0.87793 12 0.87793ZM11.6591 2.91054C11.6576 2.91096 11.6574 2.911 11.6586 2.91056C11.5094 2.96477 11.4439 3.00963 11.3855 3.06007C11.2981 3.13551 11.2065 3.24026 10.9973 3.48875C9.97906 4.69794 8.54299 6.62512 6.86377 9.50378C4.83238 12.9862 3.84405 15.9396 3.37906 17.7399C3.31457 17.9895 3.2935 18.0808 3.28588 18.1604C3.28117 18.2096 3.27951 18.2762 3.31197 18.4241L3.31284 18.4265L3.31285 18.4265C3.3154 18.4339 3.32386 18.4583 3.34309 18.501C3.37013 18.561 3.40763 18.6332 3.45189 18.7081C3.49616 18.7831 3.5413 18.8508 3.58079 18.9035C3.6089 18.9409 3.62617 18.9601 3.63137 18.9659L3.63304 18.9678C3.75701 19.0766 3.813 19.1048 3.84312 19.1184C3.89547 19.1419 3.95816 19.1608 4.17826 19.2173C5.62402 19.5883 8.10611 19.9999 12 19.9999C15.8939 19.9999 18.376 19.5883 19.8217 19.2173C20.0418 19.1608 20.1045 19.1419 20.1569 19.1184C20.187 19.1048 20.243 19.0766 20.367 18.9678C20.3669 18.9678 20.3675 18.9672 20.3686 18.9659C20.3738 18.9601 20.3911 18.9409 20.4192 18.9035C20.4587 18.8508 20.5038 18.7831 20.5481 18.7081C20.5924 18.6332 20.6299 18.561 20.6569 18.501C20.6761 18.4582 20.6846 18.4338 20.6871 18.4265L20.688 18.4241C20.7205 18.2762 20.7188 18.2096 20.7141 18.1604C20.7065 18.0808 20.6854 17.9895 20.6209 17.7399C20.1559 15.9396 19.1676 12.9862 17.1362 9.50378C15.457 6.62512 14.0209 4.69794 13.0027 3.48875C12.7935 3.24026 12.7019 3.13551 12.6145 3.06007C12.5561 3.00963 12.4906 2.96477 12.3414 2.91056C12.3419 2.91076 12.3422 2.91086 12.3422 2.91087C12.3421 2.91088 12.3417 2.91077 12.3409 2.91054C12.3344 2.90881 12.3035 2.90049 12.2432 2.89255C12.1741 2.88346 12.0899 2.87793 12 2.87793C11.9101 2.87793 11.8259 2.88346 11.7568 2.89255C11.6965 2.90049 11.6656 2.90881 11.6591 2.91054ZM10.5 15.9999C10.5 15.4476 10.9477 14.9999 11.5 14.9999H12.5C13.0523 14.9999 13.5 15.4476 13.5 15.9999V16.9999C13.5 17.5522 13.0523 17.9999 12.5 17.9999H11.5C10.9477 17.9999 10.5 17.5522 10.5 16.9999V15.9999ZM13 6.99991C13 6.44762 12.5523 5.99991 12 5.99991C11.4477 5.99991 11 6.44762 11 6.99991V12.4999C11 13.0522 11.4477 13.4999 12 13.4999C12.5523 13.4999 13 13.0522 13 12.4999V6.99991Z" fill="currentColor"></path></svg>';

// Minimum required browser versions
const minVersions = {
	chromeDesktop: 111,
	safari: 16.4,
	edge: 111,
	firefox: 112,
	opera: 97
};

// Recommended browser versions
const minValidVersions = {
	chromeDesktop: 115,
	safari: 17,
	edge: 100000,
	firefox: 115,
	opera: 100000
};

/**
 * Get browser information using UAParser
 * @returns {Object} Object containing browser name, version and other details
 */
function getBrowserInfo() {
	const parser = new UAParser();
	const parsedUA = parser.getResult();

	const browserName = parsedUA.browser.name || 'مرورگر ناشناخته';

	const browserVersion =
		parsedUA.browser.major || (parsedUA.browser.version ? parsedUA.browser.version.split('.')[0] : 'نسخه نامشخص');

	function firstTwoSegments(version) {
		return version.split('.').filter(Boolean).slice(0, 2).join('.');
	}

	return {
		name: browserName,
		version: browserVersion,
		originalName: parsedUA.browser.name,
		fullVersion: firstTwoSegments(parsedUA.browser.version || parsedUA.browser.major || 'نسخه نامشخص'),
		isAndroid: parsedUA.os.name === 'Android',
		osName: parsedUA.os.name,
		osVersion: parsedUA.os.version
	};
}

/**
 * Shows a warning message to the user based on browser compatibility
 * @param {Object} options - Configuration options for the warning message
 */
function showWarning(options) {
	const localStorageKey = `easytrader_browser_warning_dismissed_${options.browserName}`;
	const warningDismissedTimestamp = localStorage.getItem(localStorageKey);

	if (!options.isBlockerBrowser && warningDismissedTimestamp) {
		const lastDismissed = parseInt(warningDismissedTimestamp, 10);
		const now = Date.now();
		const oneMonthMs = 30 * 24 * 60 * 60 * 1000; // 30 days in ms
		if (!isNaN(lastDismissed) && now - lastDismissed < oneMonthMs) {
			return;
		}
	}

	// Get the warning div
	const warningDiv = document.getElementById('low-version-div');
	if (!warningDiv) return;

	// Create styles
	const styleButtons =
		'color: black;background-color:#efeff5;text-align: center;display: flex;justify-content: center;align-items: center;padding: 8px;border-radius: 8px;flex-grow: 1;';
	const closeButtonStyle =
		'position:absolute;top:10px;left:10px;background:none;border:none;font-size:16px;cursor:pointer;color:#333;padding:5px;';

	// Setup warning UI
	setupWarningUI(warningDiv);

	// Create UI components
	const {
		warningComponent,
		iconAlert,
		warningHeaderText,
		warningTitle,
		warningSubtitle,
		warningLinks,
		iosUpdateHelperComponent
	} = createWarningComponents(options.isBlockerBrowser);

	// Hide close button if browser is blocker
	addCloseButton(warningComponent, closeButtonStyle, warningDiv, localStorageKey, options.isBlockerBrowser);

	// Set appropriate warning message based on browser/OS
	setWarningMessage(
		options,
		warningHeaderText,
		warningSubtitle,
		warningTitle,
		warningLinks,
		iosUpdateHelperComponent,
		createLinkButton
	);

	// Construct the warning div
	constructWarningUI(
		warningDiv,
		warningComponent,
		iconAlert,
		warningHeaderText,
		warningSubtitle,
		warningTitle,
		warningLinks,
		options.isSafari && !options.isChrome ? iosUpdateHelperComponent : null
	);

	warningDiv.classList.remove('hidden');
	warningDiv.style.display = 'flex';

	/**
	 * Sets up the base warning UI container
	 * @param {HTMLElement} warningDiv - The warning container
	 */
	function setupWarningUI(warningDiv) {
		// Clear the div content for reconstructing it
		warningDiv.innerHTML = '';

		// Update the warning div style to be centered on screen
	}

	/**
	 * Creates all the UI components for the warning
	 * @param {boolean} isBlocker - is alert for blocker browsers
	 * @returns {Object} - Object containing all UI components
	 */
	function createWarningComponents(isBlocker) {
		const warningComponent = document.createElement('div');
		const iosUpdateHelperComponent = document.createElement('div');
		const iconAlert = document.createElement('div');
		const warningHeaderText = document.createElement('h2');
		const warningTitle = document.createElement('h2');
		const warningSubtitle = document.createElement('h3');
		const warningLinks = document.createElement('div');

		// Set up warning
		iconAlert.innerHTML = iconAlertSVG;
		const styleWarning =
			' --bs-bg-opacity: 1; background-color: rgba(247, 175, 62, 0.1) !important;--bs-text-opacity: 1;color: rgba(247, 175, 62, 1) !important;border-radius:16px;padding:8px';
		const styleDanger =
			' --bs-bg-opacity: 1; background-color: rgba(247, 175, 62, 0.1) !important;--bs-text-opacity: 1;color: rgb(247, 62, 62) !important;border-radius:16px;padding:8px';

		if (isBlocker) {
			iconAlert.style = styleDanger;
			iconAlert.id = 'low-version-div-icon-alert-danger';
		} else {
			iconAlert.style = styleWarning;
			iconAlert.id = 'low-version-div-icon-alert-warning';
		}

		//style warning Component
		warningComponent.style.color = 'rgba(0, 0, 0, 1)';

		warningComponent.style.backgroundColor = 'rgba(255, 255, 255, 1)';
		warningComponent.style.padding = '24px';
		warningComponent.style.borderRadius = '8px';
		warningComponent.style.display = 'flex';
		warningComponent.style.gap = '12px';
		warningComponent.style.flexDirection = 'column';
		warningComponent.style.alignItems = 'center';
		warningComponent.style.justifyContent = 'center';
		warningComponent.style.position = 'relative'; // For positioning the close button
		warningComponent.style.maxWidth = '500px'; // Limit width for better readability
		//style iosUpdateHelper Component

		iosUpdateHelperComponent.style.width = '100%';
		iosUpdateHelperComponent.style.backgroundColor = 'rgba(0, 0, 0, 0.05)';
		iosUpdateHelperComponent.style.border = 'solid 1px rgba(0, 0, 0, 0.1)';
		iosUpdateHelperComponent.style.display = 'flex';
		iosUpdateHelperComponent.style.color = 'rgb(108, 117, 125)';
		iosUpdateHelperComponent.style.gap = '3px';
		iosUpdateHelperComponent.style.flexDirection = 'column';
		iosUpdateHelperComponent.style.alignItems = 'start';
		iosUpdateHelperComponent.style.justifyContent = 'start';
		iosUpdateHelperComponent.style.alignItems = 'start';
		iosUpdateHelperComponent.style.borderRadius = '4px';
		iosUpdateHelperComponent.style.padding = '8px';
		// Style elements
		warningLinks.className = 'warning-links';
		warningLinks.style.width = '100%';
		warningLinks.style.display = 'flex';
		warningLinks.style.justifyContent = 'space-between';
		warningLinks.style.gap = '4px';
		warningLinks.style.marginTop = '15px';

		warningSubtitle.style.marginBottom = '10px';
		warningSubtitle.style.fontSize = '18px';

		warningHeaderText.style.fontSize = '20px';
		warningHeaderText.style.fontWeight = 'bold';
		warningHeaderText.style.margin = '10px 0';

		warningTitle.style.fontSize = '16px';
		warningTitle.style.fontWeight = 'bold';
		warningTitle.style.lineHeight = '1.8';
		warningTitle.style.margin = '10px 0';

		return {
			warningComponent,
			iconAlert,
			warningHeaderText,
			warningTitle,
			warningSubtitle,
			warningLinks,
			iosUpdateHelperComponent
		};
	}

	/**
	 * Adds close button to the warning
	 * @param {HTMLElement} warningComponent - The warning component container
	 * @param {string} closeButtonStyle - CSS styles for the close button
	 * @param {HTMLElement} warningDiv - The warning div
	 * @param {string} localStorageKey - The localStorage key for dismissal state
	 */
	function addCloseButton(warningComponent, closeButtonStyle, warningDiv, localStorageKey, isHidden) {
		const closeButton = document.createElement('button');
		closeButton.innerHTML = '✕';
		closeButton.id = 'low-version-div-close-button';
		closeButton.style = closeButtonStyle + (isHidden ? 'z-index: -1;' : '');
		closeButton.title = 'بستن';
		closeButton.addEventListener('click', function () {
			warningDiv.classList.add('hidden');
			warningDiv.style.display = 'none';
			// Save to localStorage the current timestamp for this warning dismissal
			localStorage.setItem(localStorageKey, Date.now().toString());
		});
		warningComponent.appendChild(closeButton);
	}

	/**
	 * Creates a button-styled link
	 * @param {string} text - Button text
	 * @param {string} href - Button URL
	 * @returns {HTMLElement} - The button element
	 */
	function createLinkButton(text, href) {
		const link = document.createElement('a');
		link.href = href;
		link.innerText = text;
		link.style = styleButtons;
		return link;
	}

	/**
	 * Sets the appropriate warning message based on browser and OS
	 */
	function setWarningMessage(
		options,
		warningHeaderText,
		warningSubtitle,
		warningTitle,
		warningLinks,
		iosUpdateHelperComponent,
		createLinkButton
	) {
		// outdated Chrome
		if (options.isChrome || options.isFirefox) {
			warningHeaderText.innerHTML = 'نسخه مرورگر شما قدیمی است';
			warningSubtitle.innerText = `مرورگر ${options.browserName} نسخه ${options.browserVersion}`;
			warningTitle.innerText = 'برای استفاده از ایزی‌تریدر، لطفاً مرورگر خود را به نسخه جدیدتر بروزرسانی کنید.';

			const updateGuideLink = createLinkButton(
				'راهنمای بروز رسانی',
				'https://learning.emofid.com/how-to-clear-cache/#update-chrome'
			);
			const supportLink = createLinkButton('تماس با پشتیبانی', 'tel:021-8700');

			if (options.isChrome) {
				warningLinks.appendChild(updateGuideLink);
			}
			warningLinks.appendChild(supportLink);
		}
		// macOS Safari with outdated version
		else if (options.isSafari) {
			warningHeaderText.innerHTML = `سیستم عامل شما نیاز به بروزرسانی دارد!`;
			warningSubtitle.innerText = `نسخه فعلی  ${options.browserFullVersion}`;
			warningTitle.innerText =
				'برای استفاده از ایزی‌تریدر، لطفاً سیستم عامل macOS خود را به نسخه جدیدتر بروزرسانی کنید. مرورگر Safari فقط از طریق بروزرسانی کلی سیستم عامل بروزرسانی می‌شود.';

			const supportLink = createLinkButton('تماس با پشتیبانی', 'tel:021-8700');
			warningLinks.appendChild(supportLink);
			const p1 = document.createElement('h4');
			const p2 = document.createElement('h4');
			const p3 = document.createElement('h4');
			const p4 = document.createElement('h4');

			p1.innerText = 'چگونه بروزرسانی کنم؟';
			p1.style.fontSize = '13px';
			p1.style.lineHeight = '1.8';
			p1.style.margin = '0';

			p2.innerText = '۱. روی منوی Apple کلیک کرده و System Settings (یا System Preferences) را انتخاب کنید';
			p2.style.fontSize = '13px';
			p2.style.lineHeight = '1.8';
			p2.style.margin = '0';

			p3.innerText = '۲. به General > Software Update بروید و در صورت وجود نسخه جدید، روی Upgrade Now کلیک کنید';
			p3.style.fontSize = '13px';
			p3.style.lineHeight = '1.8';
			p3.style.margin = '0';

			p4.innerText = '۳. پس از اتمام بروزرسانی، Safari نیز به‌صورت خودکار بروزرسانی خواهد شد';
			p4.style.fontSize = '13px';
			p4.style.lineHeight = '1.8';
			p4.style.margin = '0';

			const p5 = document.createElement('h4');
			p5.innerText = `💡 راه جایگزین: اگر امکان بروزرسانی سیستم عامل وجود ندارد، می‌توانید از مرورگر Google Chrome (نسخه ${minVersions.chromeDesktop} یا بالاتر) استفاده کنید.`;
			p5.style.fontSize = '13px';
			p5.style.lineHeight = '1.8';
			p5.style.margin = '12px 0 0 0';
			p5.style.padding = '8px';
			p5.style.backgroundColor = 'rgba(66, 133, 244, 0.1)';
			p5.style.borderRadius = '6px';
			p5.style.borderRight = '3px solid #4285f4';

			iosUpdateHelperComponent.appendChild(p1);
			iosUpdateHelperComponent.appendChild(p2);
			iosUpdateHelperComponent.appendChild(p3);
			iosUpdateHelperComponent.appendChild(p4);
			iosUpdateHelperComponent.appendChild(p5);
		}

		// Any other unsupported browser scenario
		else {
			if (options.isBlockerBrowser) {
				warningHeaderText.innerHTML = 'مرورگر شما با سیستم سازگار نیست!';
				warningSubtitle.innerText = `${options.browserName} نسخه ${options.browserVersion}`;
				warningTitle.innerText =
					'برای استفاده بهینه از سیستم ما، لطفا مرورگر خود را به کروم تغییر دهید یا با پشتیبانی ما تماس بگیرید.';
			} else {
				warningSubtitle.innerText = `مرورگر شما: ${options.browserName} نسخه ${options.browserVersion}`;
				warningTitle.innerText = `جهت کسب تجربه بهتر، از مرورگر گوگل کروم استفاده کنید.`;
			}

			const supportLink = createLinkButton('تماس با پشتیبانی', 'tel:021-8700');
			warningLinks.appendChild(supportLink);
		}
	}

	/**
	 * Gets the iOS version using UAParser
	 * @returns {string} - The iOS version
	 */
	function getIOSVersion() {
		const parser = new UAParser();
		const parsedOS = parser.getOS();

		// Check if it's iOS
		if (parsedOS.name === 'iOS') {
			// Return major version number
			const versionParts = parsedOS.version.split('.');
			return versionParts[0] || 'X';
		}

		// Check for macOS
		if (parsedOS.name === 'Mac OS') {
			const versionParts = parsedOS.version.split('.');
			return versionParts[0] || 'X';
		}

		return 'X';
	}

	/**
	 * Constructs and assembles the warning UI components
	 */
	function constructWarningUI(
		warningDiv,
		warningComponent,
		iconAlert,
		warningHeaderText,
		warningSubtitle,
		warningTitle,
		warningLinks,
		iosUpdateHelperComponent
	) {
		warningComponent.appendChild(iconAlert);
		warningComponent.appendChild(warningHeaderText);
		warningComponent.appendChild(warningSubtitle);
		warningComponent.appendChild(warningTitle);
		if (iosUpdateHelperComponent) {
			warningComponent.appendChild(iosUpdateHelperComponent);
		}
		warningComponent.appendChild(warningLinks);

		warningDiv.appendChild(warningComponent);
	}
}

/**
 * Detects browser and version, then checks compatibility using UAParser
 */
function checkBrowserVersion() {
	// Get browser information using our helper function
	const browserInfo = getBrowserInfo();

	// Extract needed values for readability
	const browserName = browserInfo.name;
	const browserVersion = browserInfo.version;
	const browserFullVersion = browserInfo.fullVersion;
	const isChrome = browserInfo.originalName.toLowerCase().includes('chrome');
	const isFirefox = browserInfo.originalName.toLowerCase().includes('firefox');
	const isSafari = browserInfo.originalName.toLowerCase().includes('safari');
	// Determine minimum valid version and if browser is valid/blocker
	let minValidVersion = '';
	let isValidBrowser = true;
	let isBlockerBrowser = false;

	// Determine browser compatibility based on name and version
	const versionNum = parseFloat(browserFullVersion, 10);
	const isVersionNumeric = !isNaN(versionNum);

	if (isChrome) {
		minValidVersion = minVersions.chromeDesktop.toString();
		isValidBrowser = isVersionNumeric && versionNum >= minValidVersions.chromeDesktop;
		isBlockerBrowser = !isVersionNumeric || versionNum < minVersions.chromeDesktop;
	} else if (isSafari) {
		minValidVersion = minVersions.safari.toString();
		isValidBrowser = isVersionNumeric && versionNum >= minValidVersions.safari;
		isBlockerBrowser = !isVersionNumeric || versionNum < minVersions.safari;
	} else if (isFirefox) {
		minValidVersion = minVersions.firefox.toString();
		isValidBrowser = isVersionNumeric && versionNum >= minValidVersions.firefox;
		isBlockerBrowser = !isVersionNumeric || versionNum < minVersions.firefox;
	} else if (browserName.toLowerCase().includes('edge')) {
		minValidVersion = minVersions.edge.toString();
		isValidBrowser = false; // Not a recommended browser
		isBlockerBrowser = !isVersionNumeric || versionNum < minVersions.edge;
	} else if (browserName.toLowerCase().includes('opera')) {
		minValidVersion = minVersions.opera.toString();
		isValidBrowser = false; // Not a recommended browser
		isBlockerBrowser = !isVersionNumeric || versionNum < minVersions.opera;
	} else {
		isValidBrowser = false;
		isBlockerBrowser = true; // Unknown browser should be considered a blocker
		minValidVersion = '?';
	}
	// If browser is not valid or is a blocking browser version, show warning
	if (!isValidBrowser || isBlockerBrowser) {
		// Add OS information from UAParser
		showWarning({
			isChrome,
			isSafari,
			isFirefox,
			isAndroid: browserInfo.isAndroid,
			browserName,
			browserVersion,
			browserFullVersion,
			osName: browserInfo.osName,
			osVersion: browserInfo.osVersion,
			minVersion: minValidVersion,
			isBlockerBrowser // pass this flag to the warning function
		});
	}
}

/**
 * Initialize browser check when the page loads
 * This will detect the browser using UAParser and show warnings if needed
 */
document.addEventListener('DOMContentLoaded', function () {
	// Make sure UAParser is loaded before running the browser check
	if (typeof UAParser === 'function') {
		checkBrowserVersion();
	} else {
		console.error('UAParser library not loaded. Browser compatibility check skipped.');
	}
});
