from opengui.skills.flat import C, R, action, skill, tag


@skill(app='com.android.settings', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.settings:navigate_to_display_size_and_text', name='navigate_to_display_size_and_text', description='Navigate to the Display size and text settings page within the Android system settings application.', created_at=1782831642.0960736, success_count=2, success_streak=2)
async def navigate_to_display_size_and_text(device):
    await action('open_app', target='com.android.settings', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.settings'})
    await action('scroll', target='settings list', valid_state='settings list is visible and scrollable', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})
    await action('tap', target='Display option', valid_state='Display option is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.settings'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.settings:id/settings_homepage_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1994})
    await action('tap', target='Display size and text option', valid_state='Display size and text option is visible and clickable', fixed=True, fixed_values={'x': 540, 'y': 2114})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_about_mastodon', name='navigate_to_about_mastodon', description="Navigate to the 'About Mastodon' section in the app settings to access web-based features.", created_at=1782837814.9192138, success_count=2, success_streak=2)
async def navigate_to_about_mastodon(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='settings button', valid_state='settings button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/settings'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 911, 'y': 201})
    await action('tap', target='About Mastodon option', valid_state='About Mastodon option is visible', fixed=True, fixed_values={'x': 303, 'y': 1387})


@skill(app='android', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:android:open_file_in_downloads', name='open_file_in_downloads', description='Open a text file in the Downloads directory and select a viewer application.', created_at=1782833572.4207454, success_count=1, success_streak=1)
async def open_file_in_downloads(device, filename):
    await action('open_app', target='android', valid_state='No need to verify', fixed=True, fixed_values={'text': 'android'})
    await action('tap', target=filename, valid_state='file is visible in the list')
    await action('tap', target='Chrome option in Open with dialog', optional=True, valid_state='Open with dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'android'}, 'signature': {'required': [{'selector': {'resource_id': 'android:id/profile_tabhost'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed_values={'text': 'Chrome', 'x': 199, 'y': 1783})


@skill(app='android', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:android:open_image_file', name='open_image_file', description='Open an image file from the Downloads folder using the Gallery app to view its content.', created_at=1782833718.3461401, success_count=1, success_streak=1)
async def open_image_file(device, file_name):
    await action('tap', target=file_name + ' file entry', valid_state='file entry is visible', fixed=True, fixed_values={'x': 287.0, 'y': 746.0})
    await action('tap', target='Gallery option in Open with dialog', optional=True, valid_state='Open with dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'android'}, 'signature': {'required': [{'selector': {'resource_id': 'android:id/profile_tabhost'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 189.0, 'y': 1927.0})


@skill(app='at.tomtasche.reader', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:at.tomtasche.reader:read_pdf_technical_details', name='read_pdf_technical_details', description='Open a PDF document and scroll through it to locate technical specifications or parameter counts.', created_at=1782842880.9758217, success_count=1, success_streak=1)
async def read_pdf_technical_details(device):
    await action('open_app', target='at.tomtasche.reader', valid_state='No need to verify', fixed=True, fixed_values={'text': 'at.tomtasche.reader'})
    await action('scroll', target='document content', valid_state='document is loaded and scrollable')
    await action('done', target='technical details located', valid_state='relevant information is visible')


@skill(app='com.android.camera2', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.camera2:take_photo', name='take_photo', description='Opens the camera application and captures a single photo.', created_at=1782844552.1742656, success_count=1, success_streak=1)
async def take_photo(device):
    await action('open_app', target='com.android.camera2', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.camera2'})
    await action('tap', target="location permission 'While using the app' button", optional=True, valid_state='location permission dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.camera2'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.camera2:id/sticky_bottom_capture_layout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1473})
    await action('tap', target='camera shutter button', valid_state='camera viewfinder is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.camera2'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.camera2:id/bottom_bar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2188})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:add_featured_hashtag', name='add_featured_hashtag', description='Adds a hashtag to the featured hashtags section in Mastodon profile via web UI.', created_at=1782835254.6634638, success_count=1, success_streak=1)
async def add_featured_hashtag(device, hashtag):
    await action('tap', target='Even more settings link', valid_state='Even more settings is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Account settings - Mastodon'}, 'state': ['visible', 'enabled', 'focused', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 219, 'y': 352})
    await action('tap', target='Toggle menu button', valid_state='Toggle menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'content_desc': 'Toggle menu'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1002, 'y': 336})
    await action('tap', target='Public profile menu item', valid_state='Public profile is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Public profile'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 224, 'y': 612})
    await action('tap', target='Featured hashtags option', valid_state='Featured hashtags is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Featured hashtags'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 285, 'y': 1012})
    await action('tap', target='Hashtag input field', valid_state='Input field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Featured hashtags - Mastodon'}, 'state': ['visible', 'enabled', 'focused', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1641})
    await action('input_text', target='Hashtag input field', text=hashtag, valid_state='Input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'featured_tag_name', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': 'cdc6ef49d6d4a7f7878cf53ff50b10544f0d7d638b9579f355289f757095be1c'}))
    await action('tap', target='Add new button', valid_state='Add new button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Add new'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1807})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:chrome_weather_search', name='chrome_weather_search', description='Search for weather information using Chrome browser', created_at=1782833465.1867452, success_count=1, success_streak=1)
async def chrome_weather_search(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='Use without an account button', optional=True, valid_state='welcome screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/signin_fre_dismiss_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2100})
    await action('tap', target='No thanks button', optional=True, valid_state='notification popup is visible', fixed=True, fixed_values={'x': 590, 'y': 1740})
    await action('tap', target='search input field', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 403})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('enter', target='keyboard enter key', valid_state='search suggestions are visible')
    await action('done', target='weather forecast section', valid_state='weather information is displayed')


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:export_mastodon_follows', name='export_mastodon_follows', description='Export follows list from Mastodon account settings via web interface.', created_at=1782838365.463691, success_count=1, success_streak=1)
async def export_mastodon_follows(device):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='Even more settings link', valid_state='About Mastodon page is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Account settings - Mastodon'}, 'state': ['visible', 'enabled', 'focused', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 219.0, 'y': 352.0})
    await action('tap', target='Toggle menu button', valid_state='Account settings page is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'content_desc': 'Toggle menu'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1002.0, 'y': 336.0})
    await action('tap', target='Import and export menu option', valid_state='Navigation menu is open', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Import and export'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 272.0, 'y': 1740.0})
    await action('tap', target='CSV download button for Follows', valid_state='Export page is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'CSV'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 803.0, 'y': 931.0})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:find_in_page_search', name='find_in_page_search', description="Search for a term within the current webpage using the 'Find in page' feature.", created_at=1782833631.9622438, success_count=1, success_streak=1)
async def find_in_page_search(device, search_query):
    await action('tap', target='Find in page menu item', valid_state='Find in page menu item is visible', fixed=True, fixed_values={'x': 640, 'y': 1363})
    await action('input_text', target=search_query, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/find_query', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8a2a7aa5a6ea5b93e0078ce234c681be724558db7e083fb31a554936bbc4ba17'}))


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:google_search', name='google_search', description='Search for a query using the Google search bar in Chrome', created_at=1782841803.5487185, success_count=1, success_streak=1)
async def google_search(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='search box', valid_state='search box is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 400})
    await action('input_text', target=query, valid_state='search box is focused')
    await action('enter', target='execute search', valid_state='keyboard is active')


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:import_muted_list', name='import_muted_list', description='Import a muted accounts list from a CSV file in Mastodon.', created_at=1782838839.929208, success_count=1, success_streak=1)
async def import_muted_list(device, file_name):
    await action('tap', target=file_name, valid_state='file picker is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Import type *'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='Upload button', valid_state='Upload button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Upload'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1687})
    await action('tap', target='Confirm button', valid_state='Confirmation dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Confirm'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 792, 'y': 948})
    await action('done', text='task finished')


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:search_arxiv_paper', name='search_arxiv_paper', description='Search for a academic paper on arXiv using the Chrome browser.', created_at=1782844379.3683915, success_count=1, success_streak=1)
async def search_arxiv_paper(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='dismiss welcome screen', optional=True, valid_state='welcome screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/signin_fre_dismiss_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2100})
    await action('tap', target='dismiss notification popup', optional=True, valid_state='notification popup is visible', fixed=True, fixed_values={'x': 590, 'y': 1740})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 403})
    await action('input_text', target=query, valid_state='search field is focused')
    await action('enter', target='execute search', valid_state='search bar is active')
    await action('tap', target='arXiv paper link', valid_state='search results are displayed', fixed=True, fixed_values={'x': 423, 'y': 1855})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:search_github_repo', name='search_github_repo', description='Search for a GitHub repository using Google and navigate to the repository page.', created_at=1782833243.6931186, success_count=1, success_streak=1)
async def search_github_repo(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='Use without an account button', optional=True, valid_state='welcome screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/signin_fre_dismiss_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2100})
    await action('tap', target="notification popup 'No thanks' button", optional=True, valid_state='notification popup is visible', fixed=True, fixed_values={'x': 590, 'y': 1740})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 393})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('enter', target='keyboard enter key', valid_state='input field is focused')
    await action('tap', target='first search result link', valid_state='search results are visible', fixed=True, fixed_values={'x': 470, 'y': 921})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:view_document_content', name='view_document_content', description='Open a document in Chrome and scroll to view its content', created_at=1782833592.2417772, success_count=1, success_streak=1)
async def view_document_content(device):
    await action('tap', target='Just once button', optional=True, valid_state='open with dialog is visible', fixed=True, fixed_values={'x': 743, 'y': 2246})
    await action('scroll', target='document content', valid_state='document content is visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:web_search', name='web_search', description='Perform a web search query in the Chrome browser.', created_at=1782844577.6004558, success_count=1, success_streak=1)
async def web_search(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='close sync suggestion popup', optional=True, valid_state='close sync suggestion popup is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/sync_promo_close_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 964, 'y': 1183})
    await action('tap', target='search input field', valid_state='search input field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 403})
    await action('input_text', target=query, valid_state='search field is focused')
    await action('enter', target='submit search query', valid_state='keyboard is active')


@skill(app='com.android.settings', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.settings:adjust_display_size', name='adjust_display_size', description='Sets the display size slider to the maximum value in the Android display settings.', created_at=1782831693.3699496, success_count=1, success_streak=1)
async def adjust_display_size(device):
    await action('open_app', target='com.android.settings', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.settings'})
    await action('tap', target='notification popup', valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.settings'}, 'signature': {'required': [{'selector': {'content_desc': 'Preview'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1334})
    await action('drag', target='Display size slider', valid_state='Display size slider is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.settings'}, 'signature': {'required': [{'selector': {'content_desc': 'Display size'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 361, 'y': 2316, 'x2': 880, 'y2': 2316})
    await action('done', target='task finished', valid_state='Display size slider is at maximum')


@skill(app='com.android.settings', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.settings:navigate_to_display_settings', name='navigate_to_display_settings', description='Navigate to the display settings menu within the system settings application.', created_at=1782831604.1522589, success_count=1, success_streak=1)
async def navigate_to_display_settings(device):
    await action('open_app', target='com.android.settings', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.settings'})
    await action('scroll', target='settings list', direction='down', pixels=400, valid_state='settings list is visible and scrollable')
    await action('tap', target='Display settings option', x=540.0, y=2004.0, valid_state='Display option is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.settings'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.settings:id/settings_homepage_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:attach_file_and_send', name='attach_file_and_send', description='Attaches a file to the current email draft and sends the email.', created_at=1782844491.4201112, success_count=1, success_streak=1)
async def attach_file_and_send(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='recent file item', valid_state='file list is visible', fixed=True, fixed_values={'x': 540, 'y': 960})
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 208})
    await action('done', target='task finished', fixed=True, fixed_values={'text': 'task finished'})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:attach_file_via_files', name='attach_file_via_files', description='Open the attachment menu in the email compose window and select the Files option to browse for documents.', created_at=1782844049.8453083, success_count=1, success_streak=1)
async def attach_file_via_files(device):
    await action('tap', target='From field', valid_state='From field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'From'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 405})
    await action('tap', target='attachment icon', valid_state='attachment icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 204})
    await action('tap', target='Files option', valid_state='Files option is visible')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:check_email_content', name='check_email_content', description='Open the mail application and locate a email by subject to verify its contents.', created_at=1782833086.7276344, success_count=1, success_streak=1)
async def check_email_content(device, email_subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email list item', valid_state='email list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'CoolHacks Registration'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:compose_email', name='compose_email', description='Compose a new email in Gmail with a recipient and subject line.', created_at=1782843243.0559106, success_count=1, success_streak=1)
async def compose_email(device, recipient, subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='compose button', valid_state='compose button is visible and clickable', fixed=True, fixed_values={'x': 820, 'y': 2020})
    await action('tap', target='To field', valid_state='To field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'To, \ue313'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 506})
    await action('input_text', target=recipient, valid_state='To field is focused')
    await action('tap', target='Subject field', valid_state='Subject field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'Subject'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 662})
    await action('input_text', target=subject, valid_state='Subject field is focused')
    await action('tap', target='attachment icon', valid_state='attachment icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 208})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:compose_email_2', name='compose_email_2', description='Open the email application and start composing a new message.', created_at=1782843314.2437236, success_count=1, success_streak=1)
async def compose_email_2(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='Compose email button', valid_state='Compose email button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 772})
    await action('tap', target='Attachment icon', valid_state='Attachment icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 208})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:compose_email_3', name='compose_email_3', description='Compose an email with a recipient, subject, and attachment.', created_at=1782843989.641542, success_count=1, success_streak=1)
async def compose_email_3(device, recipient, subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='To field', valid_state='To field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'To, \ue313'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 506})
    await action('input_text', target=recipient, valid_state='To field is focused')
    await action('tap', target='Subject field', valid_state='Subject field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'Subject'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 662})
    await action('input_text', target=subject, valid_state='Subject field is focused')
    await action('tap', target='attachment icon', valid_state='attachment icon is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:find_and_download_email_attachment', name='find_and_download_email_attachment', description='Locate an email in the Gmail app by subject, download its attachment, and open the file for viewing.', created_at=1782833674.1828523, success_count=1, success_streak=1)
async def find_and_download_email_attachment(device, email_subject, attachment_name):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('scroll', target='inbox list', valid_state='inbox is visible')
    await action('tap', target=email_subject, valid_state='email row is visible')
    await action('tap', target='download icon', valid_state='download icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\U000f01da'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('wait', target='download progress', valid_state='download completes')
    await action('tap', target=attachment_name, valid_state='attachment is visible')
    await action('long_press', target=attachment_name, valid_state='attachment is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'class': 'android.widget.TextView'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:navigate_to_awaiting_shipment', name='navigate_to_awaiting_shipment', description='Navigate to the awaiting shipment order list within the application', created_at=1782831869.0361888, success_count=1, success_streak=1)
async def navigate_to_awaiting_shipment(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='profile tab', valid_state='bottom navigation bar is visible', fixed=True, fixed_values={'x': 942, 'y': 2265})
    await action('tap', target='awaiting shipment section', valid_state='awaiting shipment option is visible', fixed=True, fixed_values={'x': 424, 'y': 952})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:open_email_by_subject', name='open_email_by_subject', description='Open a email in the Gmail clone app by locating it in the inbox.', created_at=1782833147.0409307, success_count=1, success_streak=1)
async def open_email_by_subject(device, email_subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('scroll', target='inbox list', valid_state='inbox is visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})
    await action('tap', target='email with subject ' + email_subject, valid_state='email list is visible')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:open_gmail_and_select_email', name='open_gmail_and_select_email', description='Opens the Gmail application and selects an email from the inbox.', created_at=1782844358.5951874, success_count=1, success_streak=1)
async def open_gmail_and_select_email(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email from Tony', valid_state='email is visible and clickable', fixed=True, fixed_values={'x': 540, 'y': 986})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:open_mail_and_tap_email', name='open_mail_and_tap_email', description='Opens the Gmail application and taps on a email in the inbox.', created_at=1782833385.0996256, success_count=1, success_streak=1)
async def open_mail_and_tap_email(device, email_sender):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email from ' + email_sender, valid_state='inbox is visible')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_to_email', name='reply_to_email', description="Reply to a contact's email with a custom message.", created_at=1782831575.7811081, success_count=1, success_streak=1)
async def reply_to_email(device, contact_name, reply_message):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email from ' + contact_name, valid_state='email is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Meeting Thursday'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='reply button', valid_state='reply button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 886, 'y': 523})
    await action('tap', target='compose email field', valid_state='compose field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 801})
    await action('input_text', target=reply_message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 204})
    await action('done', target='task finished', valid_state='email sent successfully')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_to_email_2', name='reply_to_email_2', description="Reply to a contact's email with a custom message", created_at=1782831745.1145709, success_count=1, success_streak=1)
async def reply_to_email_2(device, contact_name, email_subject, reply_message):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email from ' + contact_name, valid_state='email is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Meeting Thursday'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 993})
    await action('tap', target='reply button', valid_state='reply button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 886, 'y': 523})
    await action('tap', target='compose email body', valid_state='compose area is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 801})
    await action('input_text', target=reply_message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_to_email_3', name='reply_to_email_3', description='Open Gmail, reply to an email, compose a message, and initiate file attachment.', created_at=1782844461.9003425, success_count=1, success_streak=1)
async def reply_to_email_3(device, message_body):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='reply button', valid_state='reply button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 886, 'y': 523})
    await action('tap', target='compose email field', valid_state='compose email field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 801})
    await action('input_text', target=message_body, valid_state='input field is focused')
    await action('tap', target='attach file button', valid_state='attach file button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 208})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:search_email', name='search_email', description='Search for an email by keyword and open the matching message.', created_at=1782832953.7630267, success_count=1, success_streak=1)
async def search_email(device, query):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Search in mail'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 374})
    await action('input_text', target=query, valid_state='search field is focused')
    await action('tap', target='email result', valid_state='email result is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'MCFT Conference'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:send_email', name='send_email', description='Compose and send an email in Gmail to a recipient with a subject.', created_at=1782842404.6995952, success_count=1, success_streak=1)
async def send_email(device, recipient_email, subject_text):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='Compose button', valid_state='Compose button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Attachments:'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='To field', valid_state='To field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'To, \ue313'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 506})
    await action('input_text', target=recipient_email, valid_state='input field is focused')
    await action('tap', target='Subject field', valid_state='Subject field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'Subject'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 662})
    await action('input_text', target=subject_text, valid_state='input field is focused')
    await action('tap', target='Send button', valid_state='Send button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 201})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:send_email_2', name='send_email_2', description='Compose and send an email with attachments.', created_at=1782843930.9082572, success_count=1, success_streak=1)
async def send_email_2(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email body', valid_state='compose email field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540.0, 'y': 1161.0})
    await action('tap', target='send button', valid_state='send button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891.0, 'y': 208.0})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:send_email_with_attachment', name='send_email_with_attachment', description='In com.gmailclone, attaches a file to an email and sends it.', created_at=1782834294.479449, success_count=1, success_streak=1)
async def send_email_with_attachment(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='file item', valid_state='file list is visible', fixed=True, fixed_values={'x': 287, 'y': 2284})
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 208})
    await action('done', target='task finished', valid_state='email sent successfully')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:send_email_with_attachment_2', name='send_email_with_attachment_2', description='Send an email with an attachment in Gmail.', created_at=1782844110.9602046, success_count=1, success_streak=1)
async def send_email_with_attachment_2(device, contact, subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='Compose button', valid_state='Compose button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('input_text', target=contact, valid_state='To field is focused')
    await action('input_text', target=subject, valid_state='Subject field is focused')
    await action('tap', target='Attach button', valid_state='Attach button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='attachment file', valid_state='File picker is visible', fixed=True, fixed_values={'x': 540, 'y': 948})
    await action('tap', target='send button', valid_state='Send button is visible', fixed=True, fixed_values={'x': 891, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:send_email_with_attachments', name='send_email_with_attachments', description='Send an email with pre-attached media files to a recipient with a custom message.', created_at=1782844323.960018, success_count=1, success_streak=1)
async def send_email_with_attachments(device, recipient, message_body):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='To field', valid_state='To field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': 'To, \ue313'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540.0, 'y': 504.0})
    await action('input_text', target=recipient, valid_state='Input field is focused')
    await action('tap', target='Compose email body field', valid_state='Body field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540.0, 'y': 799.0})
    await action('input_text', target=message_body, valid_state='Input field is focused')
    await action('tap', target='Send button', valid_state='Send button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891.0, 'y': 204.0})
    await action('done', text='task finished')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:view_email_inbox', name='view_email_inbox', description='Open the email application, tap an email in the inbox to view its contents, and return to the home screen.', created_at=1782842989.388709, success_count=1, success_streak=1)
async def view_email_inbox(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email item in inbox', valid_state='email list is visible')
    await action('home', target='home button', valid_state='home screen is visible', fixed=True)


@skill(app='com.google.android.apps.maps', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.maps:navigate_to_cart_and_scroll', name='navigate_to_cart_and_scroll', description='Open the target application, access the shopping cart via the bottom navigation bar, and scroll through the item list to review product details.', created_at=1782832710.3381827, success_count=1, success_streak=1)
async def navigate_to_cart_and_scroll(device):
    await action('open_app', target='com.google.android.apps.maps', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.maps'})
    await action('tap', target='shopping cart icon', valid_state='shopping cart icon is visible and clickable', fixed=True, fixed_values={'x': 680.0, 'y': 2256.0})
    await action('scroll', target='shopping cart list', valid_state='cart list is displayed and scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='com.google.android.apps.maps', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.maps:search_location', name='search_location', description='Search for a location or business in Google Maps and select the primary result.', created_at=1782834376.4225602, success_count=1, success_streak=1)
async def search_location(device, query):
    await action('open_app', target='com.google.android.apps.maps', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.maps'})
    await action('tap', target='skip sign-in button', optional=True, valid_state='sign-in prompt is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'text': 'SKIP'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 954, 'y': 201})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/search_omnibox_text_box'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 218})
    await action('input_text', target=query, valid_state='search field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/search_omnibox_edit_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '19db6d6b0829f2bcf38754ecee1f8c3101abc49a76b11decf72410800938a7dc'}))
    await action('tap', target='first search result', valid_state='search results are visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/home_bottom_sheet_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 374})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:reply_to_message', name='reply_to_message', description='Reply to a message in the Google Messages app.', created_at=1782843082.648559, success_count=1, success_streak=1)
async def reply_to_message(device, message_content):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='first conversation in list', valid_state='conversation list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 441})
    await action('tap', target='close icon on banner', optional=True, valid_state='banner is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/banner_close_icon'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1017, 'y': 374})
    await action('tap', target='text input field', valid_state='input field is visible', fixed=True, fixed_values={'x': 540, 'y': 2258})
    await action('input_text', target=message_content, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/compose_message_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 977, 'y': 2143})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:reply_to_message_2', name='reply_to_message_2', description='Opens the messaging app, selects a conversation, dismisses any save-contact popup, and sends a reply message.', created_at=1782843130.312011, success_count=1, success_streak=1)
async def reply_to_message_2(device, reply_text):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='conversation list item', valid_state='conversation list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 446})
    await action('tap', target='close popup button', optional=True, valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/banner_close_icon'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1017, 'y': 381})
    await action('tap', target='message input field', valid_state='input field is visible', fixed=True, fixed_values={'x': 540, 'y': 2246})
    await action('input_text', target=reply_text, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/compose_message_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 977, 'y': 2138})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:search_location', name='search_location', description='Searches for a location or business in Google Maps and scrolls to view details.', created_at=1782834318.3433747, success_count=1, success_streak=1)
async def search_location_2(device, query):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='skip sign-in button', optional=True, valid_state='skip button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'text': 'SKIP'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 954, 'y': 204})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'text': 'Search here'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 218})
    await action('input_text', target=query, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/search_omnibox_edit_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '6dd184fe82f2bf60580058aa4f9ecb3ac698ea8b3283136aa403eda6be5d98e8'}))
    await action('tap', target='first search result', valid_state='search results are visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/home_bottom_sheet_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('scroll', target='location details section', text='down', pixels=400, valid_state='location page is loaded')


@skill(app='com.google.android.apps.wallpaper', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.wallpaper:apply_wallpaper', name='apply_wallpaper', description='Apply a selected wallpaper to the device screens.', created_at=1782832648.6201546, success_count=1, success_streak=1)
async def apply_wallpaper(device, photo_target, screen_choice):
    await action('open_app', target='com.google.android.apps.wallpaper', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.wallpaper'})
    await action('tap', target=photo_target, valid_state='photo grid is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.wallpaper'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.wallpaper:id/wallpaper_control_button_group'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='Set Wallpaper button', valid_state='preview is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.wallpaper'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.wallpaper:id/button_set_wallpaper'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 873.0, 'y': 204.0})
    await action('tap', target=screen_choice, valid_state='dialog is visible')


@skill(app='com.google.android.apps.wallpaper', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.wallpaper:navigate_to_wallpaper_selection', name='navigate_to_wallpaper_selection', description='Open the wallpaper settings app and navigate to the wallpaper selection screen.', created_at=1782832585.035508, success_count=1, success_streak=1)
async def navigate_to_wallpaper_selection(device):
    await action('open_app', target='com.google.android.apps.wallpaper', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.wallpaper'})
    await action('tap', target='More wallpapers', valid_state='More wallpapers button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.wallpaper'}, 'signature': {'required': [{'selector': {'text': 'More wallpapers'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 585, 'y': 2124})


@skill(app='com.google.android.deskclock', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.deskclock:set_alarm', name='set_alarm', description='Sets a new alarm at a specified time.', created_at=1782833194.383293, success_count=1, success_streak=1)
async def set_alarm(device, hour, minute):
    await action('open_app', target='com.google.android.deskclock', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.deskclock'})
    await action('tap', target='Alarm tab', valid_state='Alarm tab is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.deskclock'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.deskclock:id/tab_menu_alarm'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 108, 'y': 2232})
    await action('tap', target='Add alarm button', valid_state='Add alarm button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.deskclock'}, 'signature': {'required': [{'selector': {'content_desc': 'Add alarm'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1963})
    await action('input_text', target=hour + ':' + minute, valid_state='time input field is focused')
    await action('tap', target='OK button', valid_state='OK button is visible', fixed=True, fixed_values={'x': 867, 'y': 1819})


@skill(app='com.google.android.dialer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.dialer:find_contact_in_phone_app', name='find_contact_in_phone_app', description='Opens the phone application, navigates to the contacts tab, and scrolls to locate a contact.', created_at=1782838714.3730042, success_count=1, success_streak=1)
async def find_contact_in_phone_app(device):
    await action('open_app', target='com.google.android.dialer', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.dialer'})
    await action('tap', target='Contacts tab', valid_state='Contacts tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.dialer'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.dialer:id/tab_contacts'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 675, 'y': 2232})
    await action('scroll', target='contacts list', valid_state='contacts list is visible', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:extract_archive_contents', name='extract_archive_contents', description='Extracts the contents of a selected archive to the current directory.', created_at=1782833539.846864, success_count=1, success_streak=1)
async def extract_archive_contents(device):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='Extract to... menu option', valid_state='Extract to... option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 687, 'y': 573})
    await action('tap', target='EXTRACT button', valid_state='EXTRACT button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 437, 'y': 2287})
    await action('back', target='Back', valid_state='Returned to Downloads folder')


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:navigate_to_downloads', name='navigate_to_downloads', description='Navigate to the Downloads folder in the file picker application.', created_at=1782843278.110341, success_count=1, success_streak=1)
async def navigate_to_downloads(device):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='Files', optional=True, valid_state='Files option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1948})
    await action('tap', target='Show roots menu button', valid_state='Menu button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'content_desc': 'Show roots'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 73, 'y': 192})
    await action('tap', target='Downloads', valid_state='Downloads option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 259, 'y': 804})


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:open_app_drawer', name='open_app_drawer', description='Navigates to the home screen and opens the application drawer to locate applications.', created_at=1782844530.8830383, success_count=1, success_streak=1)
async def open_app_drawer(device):
    await action('tap', target='home button', valid_state='home button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'content_desc': 'Home'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 71, 'y': 204})
    await action('drag', target='screen swipe up', valid_state='home screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.nexuslauncher:id/search_container_hotseat'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2280, 'x2': 540, 'y2': 1920})


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:open_file_in_zip', name='open_file_in_zip', description='Open a file located inside a ZIP archive within the Downloads directory.', created_at=1782833501.0489907, success_count=1, success_streak=1)
async def open_file_in_zip(device, zip_name, file_name):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='ZIP archive named ' + zip_name, valid_state='ZIP archive is visible in the list', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='text file named ' + file_name, valid_state='text file is visible inside the archive', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:rename_file', name='rename_file', description='Rename a file in the Documents/Files app', created_at=1782838420.2359502, success_count=1, success_streak=1)
async def rename_file(device, new_name):
    await action('tap', target='Rename option', valid_state='Rename option is visible', fixed=True, fixed_values={'x': 664, 'y': 1094})
    await action('long_press', target='text input field', valid_state='text input field is visible and focused', fixed=True, fixed_values={'x': 540, 'y': 1248})
    await action('input_text', target=new_name, valid_state='text input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'android:id/text1', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '81031f11ed4127540570e0a4ab4f6480fd5a8082d2dd41863a3b2b20d15ccbb5'}))
    await action('tap', target='OK button', valid_state='OK button is visible', fixed=True, fixed_values={'x': 884, 'y': 1408})


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:save_file_to_directory', name='save_file_to_directory', description='Save a file to a specified directory within the Documents app.', created_at=1782844427.874688, success_count=1, success_streak=1)
async def save_file_to_directory(device, target_folder, filename):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='Save option', valid_state='toolbar is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 641.0, 'y': 458.0})
    await action('tap', target='parent folder link', valid_state='parent folder link is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target=target_folder, valid_state='folder list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='filename input field', valid_state='filename input field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 494.0, 'y': 2287.0})
    await action('input_text', target=filename, valid_state='input field is focused')


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:select_file_in_downloads', name='select_file_in_downloads', description='Open the Files app and long press a file in the Downloads folder to select it.', created_at=1782838412.791141, success_count=1, success_streak=1)
async def select_file_in_downloads(device, file_name):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('long_press', target=file_name, valid_state='Downloads folder is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'class': 'android.widget.LinearLayout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.google.android.providers.media.module', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.providers.media.module:select_image_from_picker', name='select_image_from_picker', description='Selects a image from the system photo picker to attach to a post.', created_at=1782839069.0217555, success_count=1, success_streak=1)
async def select_image_from_picker(device, image_description):
    await action('tap', target='photo picker grid', valid_state='photo picker is open', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.providers.media.module'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.providers.media.module:id/picker_tab_viewpager'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}))
    await action('tap', target=image_description, valid_state='image is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.providers.media.module'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.providers.media.module:id/picker_tab_viewpager'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}))


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:copy_message_text', name='copy_message_text', description='Copies the text content of a message within a Mattermost channel.', created_at=1782840620.4638374, success_count=1, success_streak=1)
async def copy_message_text(device, message_item):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('long_press', target=message_item, valid_state='message is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'class': 'android.view.ViewGroup'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': 'ff4618ab5ae5ceb34704aab6b70ddbc571839ce611d244783a8f1c50efe59c8a'}))
    await action('tap', target='Copy Text option', valid_state='context menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'content_desc': 'Bottom Sheet'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 251, 'y': 2148})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:navigate_to_mattermost_channel', name='navigate_to_mattermost_channel', description='Navigate to a channel in Mattermost to view messages.', created_at=1782842205.7392704, success_count=1, success_streak=1)
async def navigate_to_mattermost_channel(device, channel_name):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target=channel_name + ' channel', valid_state='channel list is visible')


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:open_direct_message', name='open_direct_message', description='Opens a direct message conversation with a contact in Mattermost.', created_at=1782842358.8962023, success_count=1, success_streak=1)
async def open_direct_message(device, contact_name):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='direct message entry for ' + contact_name, valid_state=contact_name + ' is visible in the direct messages list')


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:post_confirmation_message', name='post_confirmation_message', description='Post a confirmation message in a Mattermost channel listing created calendar events.', created_at=1782842324.1007879, success_count=1, success_streak=1)
async def post_confirmation_message(device, message_content):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='message input field', valid_state='input field is visible and enabled', fixed=True, fixed_values={'x': 540, 'y': 2188})
    await action('input_text', target=message_content, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and clickable', fixed=True, fixed_values={'x': 953, 'y': 2160})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:review_shift_requests_channel', name='review_shift_requests_channel', description='Open Mattermost and navigate to the shift-requests channel to review pending shift swap requests.', created_at=1782842506.8695512, success_count=1, success_streak=1)
async def review_shift_requests_channel(device):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='Shift Requests channel', valid_state='Shift Requests channel is visible in the sidebar', fixed=True, fixed_values={'x': 287, 'y': 1521})
    await action('scroll', target='message history', valid_state='messages are visible in the channel', fixed=True, fixed_values={'direction': 'up', 'pixels': 400})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:send_message', name='send_message', description='Sends a text message in Mattermost.', created_at=1782842419.5045989, success_count=1, success_streak=1)
async def send_message(device, message):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='message input field', valid_state='input field is visible', fixed=True, fixed_values={'x': 540, 'y': 2167})
    await action('input_text', target=message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible', fixed=True, fixed_values={'x': 951, 'y': 2167})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:awaiting_shipment_orders', name='awaiting_shipment_orders', description='Navigate to the awaiting shipment orders section in the TaoDian app.', created_at=1782832417.7471998, success_count=1, success_streak=1)
async def awaiting_shipment_orders(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='Awaiting Shipment tab', valid_state='tab is visible and clickable', fixed=True, fixed_values={'x': 290, 'y': 554})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:confirm_delete_selection', name='confirm_delete_selection', description='Confirms the deletion of selected items in a shopping cart and verifies the updated list.', created_at=1782832546.642198, success_count=1, success_streak=1)
async def confirm_delete_selection(device):
    await action('tap', target='OK button in confirmation dialog', valid_state='confirmation dialog is visible', fixed=True, fixed_values={'x': 718.0, 'y': 1380.0})
    await action('scroll', target='shopping cart item list', valid_state='cart list is visible', fixed=True, fixed_values={'direction': 'up', 'pixels': 400})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:filter_orders_by_period', name='filter_orders_by_period', description='Filter order list by time period', created_at=1782842961.676514, success_count=1, success_streak=1)
async def filter_orders_by_period(device, period):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='filter icon', valid_state='filter icon is visible', fixed=True, fixed_values={'x': 1020, 'y': 312})
    await action('tap', target=period, valid_state='filter dialog is open')
    await action('tap', target='confirm button', valid_state='confirm button is visible', fixed=True, fixed_values={'x': 794, 'y': 2232})
    await action('tap', target='all orders tab', valid_state='tab bar is visible', fixed=True, fixed_values={'x': 96, 'y': 312})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:find_awaiting_shipment_orders', name='find_awaiting_shipment_orders', description='Navigate to the awaiting shipment orders section in the TaoDian app.', created_at=1782831840.448404, success_count=1, success_streak=1)
async def find_awaiting_shipment_orders(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button', optional=True, valid_state='cash popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '3cc140c99cc090d3256e5a748a5f80352abf0037143c05a2c266bbdce8bde514'}))
    await action('tap', target='My profile tab', valid_state='home page is visible')
    await action('tap', target='My Orders menu item', valid_state='My profile page is loaded')
    await action('tap', target='Awaiting Shipment tab', valid_state='Orders page is visible')


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:locate_order_item', name='locate_order_item', description='Navigate to the order list and locate the target product order item.', created_at=1782839004.4070506, success_count=1, success_streak=1)
async def locate_order_item(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button', optional=True, valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 482})
    await action('tap', target='My profile tab', valid_state='My tab is visible', fixed=True, fixed_values={'x': 945, 'y': 2263})
    await action('tap', target='All orders button', valid_state='All orders button is visible', fixed=True, fixed_values={'x': 945, 'y': 799})
    await action('scroll', target='order list', valid_state='order list is scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})
    await action('tap', target='target order item', valid_state='target order item is visible and clickable', fixed=True, fixed_values={'x': 540, 'y': 2232})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:navigate_to_cart_and_sms_login', name='navigate_to_cart_and_sms_login', description='Open the app, navigate to the shopping cart, and switch to SMS login mode.', created_at=1782832467.860085, success_count=1, success_streak=1)
async def navigate_to_cart_and_sms_login(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='shopping cart tab', valid_state='shopping cart tab is visible', fixed=True, fixed_values={'x': 675.0, 'y': 2292.0})
    await action('tap', target='sms login option', valid_state='sms login option is visible', fixed=True, fixed_values={'x': 775.0, 'y': 799.0})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:open_app_and_dismiss_popup', name='open_app_and_dismiss_popup', description='Open the app and dismiss the promotional cash popup.', created_at=1782842895.743952, success_count=1, success_streak=1)
async def open_app_and_dismiss_popup(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button on cash popup', optional=True, valid_state='cash popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '3cc140c99cc090d3256e5a748a5f80352abf0037143c05a2c266bbdce8bde514'}))


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:open_app_and_switch_to_sms_login', name='open_app_and_switch_to_sms_login', description='Open the TaoDian shopping application and switch the login method to SMS verification code.', created_at=1782834387.8479908, success_count=1, success_streak=1)
async def open_app_and_switch_to_sms_login(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='cart tab', valid_state='bottom navigation bar is visible', fixed=True, fixed_values={'x': 675, 'y': 2292})
    await action('tap', target='sms login option', valid_state='login page is displayed', fixed=True, fixed_values={'x': 775, 'y': 806})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:open_app_dismiss_popup', name='open_app_dismiss_popup', description='Opens the TaoDian app and dismisses the initial promotional popup.', created_at=1782832682.4496725, success_count=1, success_streak=1)
async def open_app_dismiss_popup(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button on promotional popup', optional=True, valid_state='promotional popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '3cc140c99cc090d3256e5a748a5f80352abf0037143c05a2c266bbdce8bde514'}))


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:create_new_folder', name='create_new_folder', description="Create a new folder within the gallery app's move dialog.", created_at=1782842771.1959045, success_count=1, success_streak=1)
async def create_new_folder(device, folder_name):
    await action('tap', target='New Folder button', valid_state='New Folder button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'text': 'New Folder'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 127, 'y': 1552})
    await action('input_text', target=folder_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'resource_id': 'gallery.photomanager.picturegalleryapp.imagegallery:id/new_folder_et', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': 'e066c5c3af7a979f238b537be8a5cd455a95abdc1d196179629e3d493505ce93'}))


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:finalize_photo_organization', name='finalize_photo_organization', description='Finalizes photo organization by confirming permissions and returning to the main gallery view.', created_at=1782842811.4575891, success_count=1, success_streak=1)
async def finalize_photo_organization(device):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target='Allow button on permission dialog', optional=True, valid_state='permission dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'text': 'No pictures'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 801, 'y': 1466})
    await action('tap', target='Navigate up button', valid_state='back button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'content_desc': 'Navigate up'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 208})


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:move_photos_to_new_folder', name='move_photos_to_new_folder', description='Move selected photos to a newly created folder in the gallery app.', created_at=1782842713.4414334, success_count=1, success_streak=1)
async def move_photos_to_new_folder(device, folder_name):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target='Move to button', valid_state='Move to button is visible', fixed=True, fixed_values={'x': 810, 'y': 336})
    await action('tap', target='New Folder button', valid_state='New Folder button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'text': 'New Folder'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 127, 'y': 1792})
    await action('input_text', target=folder_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'resource_id': 'gallery.photomanager.picturegalleryapp.imagegallery:id/new_folder_et', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': 'e066c5c3af7a979f238b537be8a5cd455a95abdc1d196179629e3d493505ce93'}))


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:open_gallery_and_select_album', name='open_gallery_and_select_album', description='Opens the picture and wallpaper application and navigates to a album within the photo picker.', created_at=1782832620.1393328, success_count=1, success_streak=1)
async def open_gallery_and_select_album(device, album_name):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target='My photos button', valid_state='My photos button is visible', fixed=True, fixed_values={'x': 540, 'y': 660})
    await action('tap', target=album_name + ' album', valid_state='Album list is visible')


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:select_images_in_album', name='select_images_in_album', description='Open a gallery application, navigate to a specified album, and select multiple images by long-pressing the first item and tapping subsequent items.', created_at=1782844275.3026183, success_count=1, success_streak=1)
async def select_images_in_album(device, album_name, image_1, image_2, image_3, image_4):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target=album_name, valid_state='album list is visible')
    await action('long_press', target=image_1, valid_state='image grid is visible', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'class': 'android.widget.RelativeLayout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target=image_2, valid_state='image grid is visible')
    await action('tap', target=image_3, valid_state='image grid is visible')
    await action('tap', target=image_4, valid_state='image grid is visible')


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:select_photos_in_album', name='select_photos_in_album', description='Select multiple photos in the gallery album view to prepare for organization.', created_at=1782842744.9034867, success_count=1, success_streak=1)
async def select_photos_in_album(device):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target='Allow permission button', optional=True, valid_state='permission dialog is visible', fixed=True, fixed_values={'x': 801.0, 'y': 1466.0})
    await action('long_press', target='first photo thumbnail', valid_state='album view is visible', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'resource_id': 'gallery.photomanager.picturegalleryapp.imagegallery:id/picture_iv'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 135.0, 'y': 429.0})
    await action('tap', target='second photo thumbnail', valid_state='selection mode is active', fixed=True, fixed_values={'x': 405.0, 'y': 429.0})
    await action('tap', target='third photo thumbnail', valid_state='selection mode is active', fixed=True, fixed_values={'x': 675.0, 'y': 429.0})
    await action('tap', target='fourth photo thumbnail', valid_state='selection mode is active', fixed=True, fixed_values={'x': 945.0, 'y': 429.0})


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:view_photo_details', name='view_photo_details', description='Open the gallery app, navigate to an album, open a photo, and display its metadata details.', created_at=1782842664.4815543, success_count=1, success_streak=1)
async def view_photo_details(device, album_name):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target=album_name + ' album', valid_state='album grid is visible')
    await action('tap', target='a photo thumbnail', valid_state='photo grid is visible')
    await action('tap', target='info button', valid_state='photo viewer is open', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'resource_id': 'gallery.photomanager.picturegalleryapp.imagegallery:id/pull_back_layout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 720, 'y': 2212})


@skill(app='mcurrentfocus-window-2199e49-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-2199e49-u0-dropdown-menu:navigate_to_lists', name='navigate_to_lists', description='Navigate to the Lists section in the Mastodon app via the main navigation menu', created_at=1782839936.758789, success_count=1, success_streak=1)
async def navigate_to_lists(device):
    await action('tap', target='dropdown arrow next to Home', valid_state='dropdown arrow is visible and clickable', fixed=True, fixed_values={'x': 93.0, 'y': 204.0})
    await action('tap', target='Lists option in the dropdown menu', valid_state='Lists option is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-2199e49-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Lists'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 129.0, 'y': 722.0})


@skill(app='mcurrentfocus-window-62a7d1e-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-62a7d1e-u0-dropdown-menu:navigate_to_followed_hashtags', name='navigate_to_followed_hashtags', description='Navigate to the followed hashtags list in Mastodon', created_at=1782839872.2762997, success_count=1, success_streak=1)
async def navigate_to_followed_hashtags(device):
    await action('tap', target='Home dropdown menu', valid_state='Home dropdown menu is visible', fixed=True, fixed_values={'x': 95, 'y': 196})
    await action('tap', target='Followed hashtags menu item', valid_state='Followed hashtags menu item is visible', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-62a7d1e-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Followed hashtags'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 168, 'y': 866})


@skill(app='mcurrentfocus-window-7fd322a-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-7fd322a-u0-dropdown-menu:navigate_to_followed_hashtags', name='navigate_to_followed_hashtags', description='Navigate to the followed hashtags management list in Mastodon.', created_at=1782839787.3697548, success_count=1, success_streak=1)
async def navigate_to_followed_hashtags_2(device):
    await action('tap', target='Home dropdown menu', valid_state='Home header is visible', fixed=True, fixed_values={'x': 95, 'y': 196})
    await action('tap', target='Followed hashtags menu item', valid_state='dropdown menu is open', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-7fd322a-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Followed hashtags'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 168, 'y': 866})
    await action('scroll', target='hashtag list', valid_state='hashtag list is visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})


@skill(app='mcurrentfocus-window-84609a8-u0-media-viewer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-84609a8-u0-media-viewer:save_image_from_mastodon_post', name='save_image_from_mastodon_post', description='Save an image from a Mastodon post by opening it in the media viewer and downloading it.', created_at=1782842078.313857, success_count=1, success_streak=1)
async def save_image_from_mastodon_post(device, target_image):
    await action('tap', target=target_image, valid_state='image is visible and clickable')
    await action('tap', target='download button', valid_state='download button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-84609a8-u0-media-viewer'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/btn_download'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 995, 'y': 201})
    await action('done', text='task finished')


@skill(app='mcurrentfocus-window-bc6dc45-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-bc6dc45-u0-dropdown-menu:navigate_to_lists', name='navigate_to_lists', description='Navigate to the Lists section in the Mastodon app via the side menu.', created_at=1782837594.2066112, success_count=1, success_streak=1)
async def navigate_to_lists_2(device):
    await action('tap', target='side menu button', valid_state='menu button is visible', fixed=True, fixed_values={'x': 93, 'y': 201})
    await action('tap', target='Lists option in the dropdown menu', valid_state='Lists option is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-bc6dc45-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Lists'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 129, 'y': 715})


@skill(app='mcurrentfocus-window-d32cf2b-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-d32cf2b-u0-dropdown-menu:navigate_to_followed_hashtags', name='navigate_to_followed_hashtags', description='Navigate to the followed hashtags management section via the application menu.', created_at=1782839202.4434469, success_count=1, success_streak=1)
async def navigate_to_followed_hashtags_3(device):
    await action('tap', target='menu button', valid_state='menu button is visible', fixed=True, fixed_values={'x': 95, 'y': 196})
    await action('tap', target='Followed hashtags menu item', valid_state='Followed hashtags menu item is visible', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-d32cf2b-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Followed hashtags'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 168, 'y': 866})


@skill(app='mcurrentfocus-window-e9c5824-u0-popupwindow-a7c530c', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-e9c5824-u0-popupwindow-a7c530c:bookmark_mastodon_post', name='bookmark_mastodon_post', description='Bookmark a post in Mastodon by accessing the post options menu.', created_at=1782834496.4010837, success_count=1, success_streak=1)
async def bookmark_mastodon_post(device):
    await action('tap', target='post options menu button', valid_state='post options menu button is visible', fixed=True, fixed_values={'x': 1010, 'y': 1468})
    await action('tap', target='Bookmark option', valid_state='Bookmark option is visible', fixed=True, fixed_values={'x': 814, 'y': 283})


@skill(app='mcurrentfocus-window-f9f9001-u0-media-viewer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-f9f9001-u0-media-viewer:save_image_from_media_viewer', name='save_image_from_media_viewer', description='Taps an image preview to view it full-screen and then taps the download button to save the image.', created_at=1782842008.9041035, success_count=1, success_streak=1)
async def save_image_from_media_viewer(device):
    await action('tap', target='image preview', valid_state='image preview is visible', fixed=True, fixed_values={'x': 540, 'y': 1020})
    await action('tap', target='download button', valid_state='download button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-f9f9001-u0-media-viewer'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/btn_download'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 995, 'y': 201})


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:check_calendar_date', name='check_calendar_date', description='Open the calendar app and navigate to a date to view scheduled events.', created_at=1782842540.5307298, success_count=1, success_streak=1)
async def check_calendar_date(device, date):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='date cell for ' + date, valid_state='date cell is visible and clickable')


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:check_calendar_events', name='check_calendar_events', description='Opens the calendar app and allows viewing events on dates to retrieve scheduling information.', created_at=1782832920.0464797, success_count=1, success_streak=1)
async def check_calendar_events(device):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='calendar grid cell for October 4', valid_state='October 4 is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.fossify.calendar'}, 'signature': {'required': [{'selector': {'content_desc': '4 October'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1002.0, 'y': 544.0})
    await action('back', target='system back button', valid_state='month view is visible', fixed=True)
    await action('tap', target='calendar grid cell for October 11', valid_state='October 11 is visible and clickable', fixed=True, fixed_values={'x': 1002.0, 'y': 852.0})


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:navigate_calendar_to_previous_month', name='navigate_calendar_to_previous_month', description='Navigate the calendar view to the previous month to review scheduled events.', created_at=1782842616.395477, success_count=1, success_streak=1)
async def navigate_calendar_to_previous_month(device):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='previous month arrow', valid_state='calendar view is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.fossify.calendar'}, 'signature': {'required': [{'selector': {'resource_id': 'org.fossify.calendar:id/top_left_arrow'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 367})


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:open_calendar_and_view_date', name='open_calendar_and_view_date', description='Opens the Fossify Calendar app and navigates to a date to view scheduled events.', created_at=1782832827.4029808, success_count=1, success_streak=1)
async def open_calendar_and_view_date(device, param1):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target=param1, valid_state='calendar month view is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.fossify.calendar'}, 'signature': {'required': [{'selector': {'content_desc': '7 October'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:open_calendar_and_view_event', name='open_calendar_and_view_event', description='Open the calendar application and tap on an event to view its details.', created_at=1782832751.6064677, success_count=1, success_streak=1)
async def open_calendar_and_view_event(device):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='calendar event', valid_state='event is visible and clickable', fixed=True, fixed_values={'x': 312, 'y': 1168})


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:view_calendar_events', name='view_calendar_events', description='Opens the Fossify Calendar app and displays the schedule for a specified date.', created_at=1782833058.1283252, success_count=1, success_streak=1)
async def view_calendar_events(device, target_date):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='calendar grid cell for ' + target_date, valid_state='date cell is visible and clickable')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:back_to_hashtag_feed_and_scroll', name='back_to_hashtag_feed_and_scroll', description='Navigate back from a post detail view to the hashtag feed and scroll down to view more posts.', created_at=1782837570.7121835, success_count=1, success_streak=1)
async def back_to_hashtag_feed_and_scroll(device):
    await action('tap', target='Back button', valid_state='Back button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Back'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 201})
    await action('scroll', target='hashtag feed', valid_state='feed is visible', fixed_values={'text': 'down', 'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:bookmark_posts_on_profile', name='bookmark_posts_on_profile', description='Search for a user on Mastodon, navigate to their profile, and bookmark their posts.', created_at=1782834611.1386054, success_count=1, success_streak=1)
async def bookmark_posts_on_profile(device, user_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='search button', valid_state='search button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('input_text', target=user_name, valid_state='search field is focused')
    await action('tap', target='user profile result', valid_state='user profile result is visible')
    await action('tap', target='post options menu', valid_state='post options menu is visible', fixed=True, fixed_values={'x': 814, 'y': 571})
    await action('tap', target='bookmark option', valid_state='bookmark option is visible')
    await action('scroll', target='timeline', pixels=400, direction='down', valid_state='timeline is scrollable')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:compose_post', name='compose_post', description='Compose a new post by entering text content', created_at=1782839024.1542847, success_count=1, success_streak=1)
async def compose_post(device, post_content):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='New post button', valid_state='New post button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'New post'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 964, 'y': 2006})
    await action('tap', target='text input field', valid_state='text input field is visible', fixed=True, fixed_values={'x': 540, 'y': 607})
    await action('input_text', target=post_content, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:create_list', name='create_list', description='Creates a new Mastodon list with a specified name.', created_at=1782837636.6514227, success_count=1, success_streak=1)
async def create_list(device, list_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Create list menu item', valid_state='Lists submenu is visible', fixed=True, fixed_values={'x': 178, 'y': 902})
    await action('tap', target='List name input field', valid_state='List name field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 379})
    await action('input_text', target=list_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:create_mastodon_list', name='create_mastodon_list', description='Navigate to list management and initiate list creation by entering a name.', created_at=1782839980.7252452, success_count=1, success_streak=1)
async def create_mastodon_list(device, list_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Manage lists menu item', valid_state='Lists submenu is visible', fixed=True, fixed_values={'x': 203, 'y': 1065})
    await action('tap', target='Create list floating action button', valid_state='Create list button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Create list'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 964, 'y': 2188})
    await action('tap', target='List name input field', valid_state='List name field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 374})
    await action('input_text', target=list_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:edit_image_alt_text', name='edit_image_alt_text', description='Edit the alt text of an image in a Mastodon post by adding a prefix to the existing text.', created_at=1782841915.7934196, success_count=1, success_streak=1)
async def edit_image_alt_text(device, prefix_text):
    await action('tap', target='Edit option in context menu', valid_state='context menu is visible', fixed=True, fixed_values={'x': 642.0, 'y': 1185.0})
    await action('tap', target='Edit alt text button', valid_state='edit button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 784.0, 'y': 1355.0})
    await action('tap', target='Start of alt text input field', valid_state='alt text input field is visible', fixed=True, fixed_values={'x': 87.0, 'y': 787.0})
    await action('input_text', target=prefix_text, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))
    await action('tap', target='Back button', valid_state='back button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Back'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72.0, 'y': 204.0})
    await action('tap', target='Save button', valid_state='save button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Save'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1016.0, 'y': 204.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:favorite_post', name='favorite_post', description='Favorite a post on Mastodon by tapping the star icon and returning to the feed.', created_at=1782837441.0115995, success_count=1, success_streak=1)
async def favorite_post(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='star icon', valid_state='post detail view is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 695, 'y': 1754})
    await action('tap', target='back button', valid_state='post detail view is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Back'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 201})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_bookmarks', name='navigate_to_bookmarks', description='Navigate to the Bookmarks section in the Mastodon Android app.', created_at=1782835286.1652534, success_count=1, success_streak=1)
async def navigate_to_bookmarks(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab', valid_state='Profile tab is visible', fixed=True, fixed_values={'x': 945, 'y': 2220})
    await action('tap', target='Saved tab', valid_state='Saved tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Saved'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 945, 'y': 1154})
    await action('tap', target='Bookmarks tab', valid_state='Bookmarks tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'text': 'Bookmarks'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 479, 'y': 1576})
    await action('tap', target='First bookmarked post', valid_state='Bookmarked post is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_saved'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1900})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_hashtags_tab', name='navigate_to_hashtags_tab', description='Navigate to the hashtags tab in the Explore section of Mastodon.', created_at=1782839178.7255177, success_count=1, success_streak=1)
async def navigate_to_hashtags_tab(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile icon', valid_state='profile icon is visible', fixed=True, fixed_values={'x': 945, 'y': 2232})
    await action('tap', target='Explore icon', valid_state='explore icon is visible', fixed=True, fixed_values={'x': 405, 'y': 2232})
    await action('tap', target='Hashtags tab', valid_state='hashtags tab is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'text': 'Hashtags'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 422, 'y': 420})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_mastodon_web_settings', name='navigate_to_mastodon_web_settings', description='Navigate to the Mastodon web settings interface via the Android app to configure advanced options like language filters.', created_at=1782838515.8680618, success_count=1, success_streak=1)
async def navigate_to_mastodon_web_settings(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='settings gear icon', valid_state='settings menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/settings'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 911, 'y': 201})
    await action('tap', target='About Mastodon option', valid_state='About Mastodon option is visible', fixed=True, fixed_values={'x': 303, 'y': 1408})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_oldest_post', name='navigate_to_oldest_post', description="Navigate to the user's profile in Mastodon and scroll to the bottom to locate the oldest published post.", created_at=1782841217.2118762, success_count=1, success_streak=1)
async def navigate_to_oldest_post(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab', valid_state='Profile tab is visible and clickable', fixed=True, fixed_values={'x': 945, 'y': 2220})
    await action('scroll', target='timeline', valid_state='timeline is visible and scrollable', fixed=True, fixed_values={'text': 'down', 'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_orders', name='navigate_to_orders', description='Navigate to the orders section within the application to review transaction history.', created_at=1782842927.6394837, success_count=1, success_streak=1)
async def navigate_to_orders(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='profile tab', valid_state='profile tab is visible and clickable', fixed=True, fixed_values={'x': 942, 'y': 2270})
    await action('tap', target='all orders option', valid_state='all orders option is visible and clickable', fixed=True, fixed_values={'x': 942, 'y': 794})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_profile', name='navigate_to_profile', description="Open the Mastodon app and navigate to the user's profile page.", created_at=1782835984.552357, success_count=1, success_streak=1)
async def navigate_to_profile(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab', valid_state='Profile tab is visible and clickable', fixed=True, fixed_values={'x': 945, 'y': 2220})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_user_profile', name='navigate_to_user_profile', description="Navigate to a user's profile in Mastodon by searching for their username.", created_at=1782834468.0473247, success_count=1, success_streak=1)
async def navigate_to_user_profile(device, username):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible and clickable', fixed=True, fixed_values={'x': 405, 'y': 2215})
    await action('tap', target='search bar', valid_state='search bar is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 247})
    await action('input_text', target=username, valid_state='search field is focused')
    await action('tap', target='user ' + username, valid_state='user result is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_bookmarked_post', name='open_bookmarked_post', description='Open a bookmarked post from the saved list to view its details.', created_at=1782835362.86595, success_count=1, success_streak=1)
async def open_bookmarked_post(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='close button', optional=True, valid_state='image viewer is open', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'text': 'TEST'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 83, 'y': 208})
    await action('tap', target='bookmarked post text area', valid_state='bookmark list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_saved'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1132})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_mastodon_web_settings', name='open_mastodon_web_settings', description='Navigate to the Mastodon web settings page to configure account preferences.', created_at=1782837148.5819247, success_count=1, success_streak=1)
async def open_mastodon_web_settings(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='settings button', valid_state='settings button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/settings'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 911, 'y': 204})
    await action('tap', target='About Mastodon menu item', valid_state='About Mastodon menu item is visible and clickable', fixed=True, fixed_values={'x': 303, 'y': 1382})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_post_from_feed', name='open_post_from_feed', description='Open a post from a hashtag feed to view details.', created_at=1782837476.1302314, success_count=1, success_streak=1)
async def open_post_from_feed(device, post_text):
    await action('tap', target='back button', optional=True, valid_state='image viewer is open', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Back'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 83.0, 'y': 201.0})
    await action('tap', target='post containing text ' + post_text, valid_state='post is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_post_in_hashtag_feed', name='open_post_in_hashtag_feed', description='Opens a post in the Mastodon app by searching for a hashtag and scrolling to the post.', created_at=1782837395.786865, success_count=1, success_streak=1)
async def open_post_in_hashtag_feed(device, query, item):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('input_text', target='search field', text=query, valid_state='search field is visible')
    await action('enter', target='search field', valid_state='search field is focused')
    await action('scroll', target='hashtag feed', text='down', pixels=400, direction='down', valid_state='feed is visible')
    await action('tap', target=item, valid_state='post is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:post_mastodon_message', name='post_mastodon_message', description='Compose and input text into a new Mastodon post.', created_at=1782840629.9388468, success_count=1, success_streak=1)
async def post_mastodon_message(device, message_text):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='compose button', valid_state='compose button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'New post'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 964, 'y': 2004})
    await action('tap', target='text input field', valid_state='text input field is visible', fixed=True, fixed_values={'x': 540, 'y': 607})
    await action('input_text', target=message_text, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:post_toot', name='post_toot', description='Compose and publish a new toot in the Mastodon app', created_at=1782841180.6890452, success_count=1, success_streak=1)
async def post_toot(device, content):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='New post button', valid_state='New post button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'New post'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 964, 'y': 2016})
    await action('tap', target='text input field', valid_state='text input field is visible', fixed=True, fixed_values={'x': 540, 'y': 604})
    await action('input_text', target=content, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text', 'class': 'android.widget.EditText'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))
    await action('tap', target='publish button', valid_state='publish button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Publish'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1016, 'y': 201})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:process_bookmarked_post', name='process_bookmarked_post', description='Removes a bookmark from a post, adds it to favorites, and boosts it.', created_at=1782835928.5469668, success_count=1, success_streak=1)
async def process_bookmarked_post(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='remove bookmark menu item', valid_state='menu is visible', fixed=True, fixed_values={'x': 779.0, 'y': 439.0})
    await action('tap', target='favorite button', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 694.0, 'y': 2112.0})
    await action('tap', target='boost button', valid_state='boost button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/boost_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 380.0, 'y': 2112.0})
    await action('back', target='back navigation', valid_state='post view is active')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:process_bookmarked_post_2', name='process_bookmarked_post_2', description='Removes the bookmark from the current post, adds it to favorites, and boosts it.', created_at=1782835952.1950474, success_count=1, success_streak=1)
async def process_bookmarked_post_2(device):
    await action('tap', target='Remove bookmark option', valid_state='menu is open with Remove bookmark visible', fixed=True, fixed_values={'x': 765, 'y': 439})
    await action('scroll', target='action bar area', valid_state='action bar is not fully visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})
    await action('tap', target='favorite button', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 694, 'y': 2059})
    await action('tap', target='boost button', valid_state='boost button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/boost_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 380, 'y': 2059})
    await action('back', target='back navigation', valid_state='post view is active')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:publish_mastodon_post', name='publish_mastodon_post', description='Post a status update on Mastodon with followers-only visibility.', created_at=1782841172.5516791, success_count=1, success_streak=1)
async def publish_mastodon_post(device, content):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='compose button', valid_state='compose button is visible')
    await action('input_text', target=content, valid_state='input field is focused')
    await action('tap', target='visibility dropdown', valid_state='visibility dropdown is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Publish'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='Followers visibility option', valid_state='Followers option is visible', fixed=True, fixed_values={'x': 259, 'y': 1008})
    await action('tap', target='Publish button', valid_state='Publish button is visible and clickable', fixed=True, fixed_values={'x': 1015, 'y': 201})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:publish_post_with_image', name='publish_post_with_image', description='Publish a post with attached image on Mastodon.', created_at=1782839129.4382515, success_count=1, success_streak=1)
async def publish_post_with_image(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Add (1) button', valid_state='image is selected', fixed=True, fixed_values={'x': 920, 'y': 2246})
    await action('tap', target='Publish button', valid_state='publish button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Publish'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1016, 'y': 196})
    await action('scroll', target='Home feed', valid_state='Home feed is visible', fixed=True, fixed_values={'pixels': 400, 'direction': 'up'})
    await action('done', target='task finished', fixed=True, fixed_values={'text': 'task finished'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:replace_profile_header', name='replace_profile_header', description='Replaces the profile header image in Mastodon by accessing the edit profile menu and selecting a new image.', created_at=1782836533.1708906, success_count=1, success_streak=1)
async def replace_profile_header(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Edit profile button', valid_state='Edit profile button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 479, 'y': 1046})
    await action('tap', target='header image area', valid_state='header image is visible', fixed=True, fixed_values={'x': 83, 'y': 208})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:replace_profile_header_2', name='replace_profile_header_2', description='Replace the profile header image with a specified photo in Mastodon.', created_at=1782836602.8201597, success_count=1, success_streak=1)
async def replace_profile_header_2(device, param1):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab', valid_state='home feed is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_about'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='Edit profile button', valid_state='profile page is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_actions'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='header image', valid_state='edit mode is active')
    await action('tap', target=param1, valid_state='photo gallery is open')
    await action('tap', target='Save changes button', valid_state='save button is visible', fixed=True, fixed_values={'x': 540, 'y': 1312})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:scroll_profile_timeline', name='scroll_profile_timeline', description="Scroll through a user's timeline to view posts.", created_at=1782834649.7185662, success_count=1, success_streak=1)
async def scroll_profile_timeline(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='background to close menu', optional=True, valid_state='menu is open', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_timeline'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 270, 'y': 720})
    await action('scroll', target='timeline feed', valid_state='timeline is visible', fixed=True, fixed_values={'text': 'down', 'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_and_follow_user', name='search_and_follow_user', description='Search for a user by username on Mastodon and follow their profile.', created_at=1782838742.0758648, success_count=1, success_streak=1)
async def search_and_follow_user(device, username):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 405, 'y': 2232})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 247})
    await action('input_text', target=username, valid_state='search field is focused')
    await action('tap', target='user account result', valid_state='user result is visible')
    await action('tap', target='Follow button', valid_state='Follow button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 479, 'y': 1003})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_hashtag_feed', name='search_hashtag_feed', description='Search for a hashtag on Mastodon and navigate to the corresponding posts feed.', created_at=1782837221.9795332, success_count=1, success_streak=1)
async def search_hashtag_feed(device, hashtag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 405, 'y': 2220})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 242})
    await action('input_text', target=hashtag, valid_state='input field is focused')
    await action('tap', target='search result for posts with the hashtag', valid_state='search suggestions are visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_mastodon_posts', name='search_mastodon_posts', description='Search Mastodon for a query or hashtag to view related posts.', created_at=1782837723.1453607, success_count=1, success_streak=1)
async def search_mastodon_posts(device, query):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 405, 'y': 2220})
    await action('tap', target='search bar', valid_state='search bar is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 242})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('tap', target='Posts with query filter', valid_state='filter option is visible', fixed=True, fixed_values={'x': 540, 'y': 415})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_user_and_open_post', name='search_user_and_open_post', description='Search for a user by name, navigate to their profile, and open a post identified by a description.', created_at=1782841973.1754704, success_count=1, success_streak=1)
async def search_user_and_open_post(device, username, post_description):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 405, 'y': 2220})
    await action('tap', target='Search bar', valid_state='Search bar is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 247})
    await action('input_text', target=username, valid_state='Input field is focused')
    await action('tap', target=username + ' profile', valid_state='User profile result is visible')
    await action('scroll', target='Timeline', valid_state='Timeline is scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})
    await action('tap', target=post_description, valid_state='Post is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_timeline'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:set_brightness_minimum', name='set_brightness_minimum', description='Set the display brightness to the minimum level.', created_at=1782831613.188358, success_count=1, success_streak=1)
async def set_brightness_minimum(device):
    await action('tap', target='Brightness level', valid_state='Brightness level is visible', fixed=True, fixed_values={'x': 540, 'y': 840})
    await action('drag', target='brightness slider', valid_state='brightness slider is visible', fixed=True, fixed_values={'x': 540, 'y': 216, 'x2': 54, 'y2': 216})
    await action('done', text='task finished')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:unfollow_hashtag', name='unfollow_hashtag', description='Unfollow a hashtag from the followed hashtags list in Mastodon.', created_at=1782839754.719518, success_count=1, success_streak=1)
async def unfollow_hashtag(device, hashtag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target=hashtag, valid_state='hashtag ' + hashtag + ' is visible in the list')
    await action('tap', target='Following button', valid_state='Following button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/follow_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 914.0, 'y': 324.0})
    await action('back', valid_state='back navigation is available')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:unfollow_hashtag_2', name='unfollow_hashtag_2', description='Unfollows a hashtag in Mastodon by navigating to its page and toggling the follow status.', created_at=1782839855.6715639, success_count=1, success_streak=1)
async def unfollow_hashtag_2(device, hashtag_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='#' + hashtag_name, valid_state='hashtag link is visible')
    await action('tap', target='Following button', valid_state='Following button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/follow_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 914, 'y': 324})
    await action('back', target='return to previous screen', valid_state='previous screen is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:view_announcements_channel', name='view_announcements_channel', description='Navigate to and view the announcements channel in the Mastodon mobile application.', created_at=1782840594.376483, success_count=1, success_streak=1)
async def view_announcements_channel(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Announcements channel', valid_state='channel list is visible', fixed=True, fixed_values={'x': 313.0, 'y': 892.0})
    await action('scroll', target='message list area', valid_state='message list is loaded', fixed=True, fixed_values={'direction': 'up', 'pixels': 400})
