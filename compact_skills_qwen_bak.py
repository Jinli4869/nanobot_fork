from opengui.skills.flat import C, R, action, skill, tag


@skill(app='com.android.camera2', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.camera2:take_photo', name='take_photo', description='Opens the camera application and captures a photo by tapping the shutter button.', created_at=1780854017.3433895, success_count=1, success_streak=1)
async def take_photo(device):
    await action('open_app', target='com.android.camera2', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.camera2'})
    await action('tap', target='location permission option', optional=True, valid_state='permission dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.camera2'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.camera2:id/sticky_bottom_capture_layout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1468})
    await action('tap', target='shutter button', valid_state='shutter button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.camera2'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.camera2:id/bottom_bar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2176})


@skill(app='com.android.camera2', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.camera2:take_photo_2', name='take_photo_2', description='Opens the camera app and captures a photo.', created_at=1780854052.2194104, success_count=1, success_streak=1)
async def take_photo_2(device):
    await action('open_app', target='com.android.camera2', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.camera2'})
    await action('tap', target='shutter button', valid_state='camera viewfinder is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.camera2'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.camera2:id/bottom_bar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2184})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:import_muted_list', name='import_muted_list', description='Navigates to the Mastodon web import settings and selects the muted list type.', created_at=1780851029.2665827, success_count=1, success_streak=1)
async def import_muted_list(device):
    await action('tap', target='Even more settings', valid_state='web UI is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Account settings - Mastodon'}, 'state': ['visible', 'enabled', 'focused', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 216, 'y': 355})
    await action('tap', target='Toggle menu', valid_state='hamburger menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'content_desc': 'Toggle menu'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1013, 'y': 355})
    await action('tap', target='Import and export', valid_state='Import and export option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Import and export'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 286, 'y': 1752})
    await action('tap', target='Toggle menu', valid_state='hamburger menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'content_desc': 'Toggle menu'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1013, 'y': 355})
    await action('tap', target='Import', valid_state='Import option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Import'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 216, 'y': 1500})
    await action('tap', target='Import type', valid_state='Import type dropdown is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Import type *'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 518, 'y': 948})
    await action('tap', target='Muting list', valid_state='Muting list option is visible', fixed=True, fixed_values={'x': 270, 'y': 1488})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:navigate_to_url', name='navigate_to_url', description='Navigate to a web address in Chrome', created_at=1780853850.7577283, success_count=1, success_streak=1)
async def navigate_to_url(device, url):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='address bar', valid_state='address bar is visible', fixed=True, fixed_values={'x': 534, 'y': 204})
    await action('input_text', target=url, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.android.chrome:id/url_bar'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '577c87ef3befb80a2d3bb87d41f84ec0c034e55e8aadb4f3be1735c9b3a254c7'}))


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:open_mastodon_preferences', name='open_mastodon_preferences', description='Navigates to the Mastodon preferences menu from the account settings page.', created_at=1780850948.5222223, success_count=1, success_streak=1)
async def open_mastodon_preferences(device):
    await action('tap', target='menu toggle button', valid_state='menu button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'content_desc': 'Toggle menu'}, 'state': ['visible', 'clickable', 'enabled', 'focused']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1004.0, 'y': 348.0})
    await action('tap', target='preferences option', valid_state='preferences option is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'text': 'Preferences'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 216.0, 'y': 739.0})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:search_github_repository', name='search_github_repository', description='Search for a GitHub repository using the Chrome browser and navigate to the repository page.', created_at=1780848779.20861, success_count=1, success_streak=1)
async def search_github_repository(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='dismiss account setup button', optional=True, valid_state='account setup dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/signin_fre_dismiss_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2090})
    await action('tap', target='dismiss notification popup', optional=True, valid_state='notification popup is visible', fixed=True, fixed_values={'x': 577, 'y': 1742})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 432, 'y': 405})
    await action('input_text', target=query, valid_state='search field is focused')
    await action('enter', valid_state='search field is focused')
    await action('tap', target='first search result link', valid_state='search results are displayed', fixed=True, fixed_values={'x': 334, 'y': 928})


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:search_in_chrome', name='search_in_chrome', description='Search for a query in the Chrome browser.', created_at=1780852592.835042, success_count=1, success_streak=1)
async def search_in_chrome(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='search input field', valid_state='search field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 324, 'y': 408})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('enter', target='search bar', valid_state='search bar is focused')
    await action('done')


@skill(app='com.android.chrome', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.android.chrome:search_in_chrome_2', name='search_in_chrome_2', description='Search for a query in the Chrome browser.', created_at=1780853790.1176612, success_count=1, success_streak=1)
async def search_in_chrome_2(device, query):
    await action('open_app', target='com.android.chrome', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.android.chrome'})
    await action('tap', target='Use without an account button', optional=True, valid_state='welcome screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/signin_fre_dismiss_button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 2090})
    await action('tap', target='No thanks button', optional=True, valid_state='notification prompt is visible', fixed=True, fixed_values={'x': 612, 'y': 1749})
    await action('tap', target='search input field', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.android.chrome'}, 'signature': {'required': [{'selector': {'resource_id': 'com.android.chrome:id/search_box_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 438, 'y': 405})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('enter', target='search query', valid_state='keyboard is active')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:compose_and_send_email', name='compose_and_send_email', description='Compose and send an email to a recipient with a message', created_at=1780853759.6093013, success_count=1, success_streak=1)
async def compose_and_send_email(device, recipient, message):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='recipient input field', valid_state='recipient field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Enter email address'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 324, 'y': 504})
    await action('input_text', target=recipient, valid_state='input field is focused')
    await action('tap', target='email body field', valid_state='email body field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 216, 'y': 792})
    await action('input_text', target=message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 891, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:compose_email_with_attachment', name='compose_email_with_attachment', description='Compose a new email with a recipient and subject, then open the attachment menu.', created_at=1780853494.107165, success_count=1, success_streak=1)
async def compose_email_with_attachment(device, recipient, subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='Compose button', valid_state='Compose button is visible and clickable', fixed=True, fixed_values={'x': 810, 'y': 2011})
    await action('tap', target='To field', valid_state='To field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Enter email address'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 302, 'y': 499})
    await action('input_text', target=recipient, valid_state='input field is focused')
    await action('tap', target='Subject field', valid_state='Subject field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Subject'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 270, 'y': 660})
    await action('input_text', target=subject, valid_state='input field is focused')
    await action('tap', target='Attachment button', valid_state='Attachment button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 775, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:confirm_attachment_and_send', name='confirm_attachment_and_send', description='Select an attachment file, send the email, and verify it appears in the Sent folder.', created_at=1780854006.3857265, success_count=1, success_streak=1)
async def confirm_attachment_and_send(device, attachment_file):
    await action('tap', target=attachment_file, valid_state='file selection screen is visible')
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 888, 'y': 204})
    await action('tap', target='menu icon', valid_state='menu icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue5c4'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 73, 'y': 204})
    await action('tap', target='navigation icon', valid_state='navigation icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue5d2'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 84, 'y': 204})
    await action('tap', target='Sent folder', valid_state='Sent folder is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Sent'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 444, 'y': 1159})
    await action('tap', target='sent email', valid_state='sent email is visible')
    await action('done', text='task finished')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:open_email_and_report', name='open_email_and_report', description='Open the email application, tap on an email from a sender, and report the extracted information.', created_at=1780849006.0342226, success_count=1, success_streak=1)
async def open_email_and_report(device, sender_name, result_text):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email from ' + sender_name, valid_state='email from sender is visible')
    await action('done', target=result_text, valid_state='task completed')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:open_email_by_subject', name='open_email_by_subject', description='Open the email application and locate a email by scrolling through the inbox.', created_at=1780848696.7805905, success_count=1, success_streak=1)
async def open_email_by_subject(device, email_subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('scroll', target='inbox list', valid_state='inbox is visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})
    await action('tap', target=email_subject + ' email', valid_state='email is visible')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:read_email', name='read_email', description='Opens the Gmail application and reads the content of a email identified by its subject.', created_at=1780853176.3490634, success_count=1, success_streak=1)
async def read_email(device, email_subject):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email with subject ' + email_subject, valid_state='email is visible and clickable')


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_email_with_attachment', name='reply_email_with_attachment', description='Reply to an email with text content and initiate file attachment.', created_at=1780853939.137708, success_count=1, success_streak=1)
async def reply_email_with_attachment(device, email_subject, reply_content):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email with subject ' + email_subject, valid_state='email is visible in inbox')
    await action('tap', target='reply button', valid_state='reply button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 883, 'y': 525})
    await action('tap', target='compose email field', valid_state='compose field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 162, 'y': 804})
    await action('input_text', target=reply_content, valid_state='input field is focused')
    await action('tap', target='attach file button', valid_state='attach button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\U000f0066'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 778, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_to_email', name='reply_to_email', description='Reply to an email by locating it via subject, typing a message, and sending it.', created_at=1780848296.69664, success_count=1, success_streak=1)
async def reply_to_email(device, subject, message):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email with subject ' + subject, valid_state='email with subject ' + subject + ' is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Meeting Thursday'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='reply button', valid_state='reply button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 888, 'y': 518})
    await action('tap', target='compose email field', valid_state='compose field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 180, 'y': 801})
    await action('input_text', target=message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 888, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:reply_to_email_2', name='reply_to_email_2', description='Open the mail app, locate an email by subject, reply to it with a message, and send it.', created_at=1780848325.2102857, success_count=1, success_streak=1)
async def reply_to_email_2(device, email_subject, message_body):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('tap', target='email with subject ' + email_subject, valid_state='email list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Meeting Thursday'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='reply button', valid_state='reply button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'content_desc': '\ue612'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 880, 'y': 516})
    await action('tap', target='compose text area', valid_state='compose screen is active', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': 'Compose email'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 178, 'y': 801})
    await action('input_text', target=message_body, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.gmailclone'}, 'signature': {'required': [{'selector': {'text': '\ue163'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 888, 'y': 204})


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:scroll_inbox', name='scroll_inbox', description='Open the mail application and scroll through the inbox to locate a message.', created_at=1780853245.1945376, success_count=1, success_streak=1)
async def scroll_inbox(device):
    await action('open_app', target='com.gmailclone', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.gmailclone'})
    await action('back', target='back button', valid_state='email detail view is visible')
    await action('scroll', target='inbox list', valid_state='inbox is visible')


@skill(app='com.google.android.apps.maps', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.maps:search_driving_directions', name='search_driving_directions', description='Search for driving directions between two locations in Google Maps.', created_at=1780854074.6984894, success_count=1, success_streak=1)
async def search_driving_directions(device, origin, destination):
    await action('open_app', target='com.google.android.apps.maps', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.maps'})
    await action('tap', target='skip sign-in button', optional=True, valid_state='skip button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'text': 'SKIP'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 965, 'y': 194})
    await action('tap', target='search bar', valid_state='search bar is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'text': 'Search here'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 324, 'y': 208})
    await action('input_text', target='search input field', text='driving directions from ' + origin + ' to ' + destination, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.maps:id/search_omnibox_edit_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '19db6d6b0829f2bcf38754ecee1f8c3101abc49a76b11decf72410800938a7dc'}))
    await action('tap', target='search suggestion', valid_state='search suggestion is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/home_bottom_sheet_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 486, 'y': 364})


@skill(app='com.google.android.apps.maps', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.maps:search_location_details', name='search_location_details', description='Search for a location in Google Maps and scroll through its details.', created_at=1780849085.2283223, success_count=1, success_streak=1)
async def search_location_details(device, query):
    await action('open_app', target='com.google.android.apps.maps', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.maps'})
    await action('tap', target='skip button', optional=True, valid_state='skip button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'text': 'SKIP'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 960, 'y': 194})
    await action('tap', target='search input field', valid_state='search field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'text': 'Search here'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 405, 'y': 211})
    await action('input_text', target=query, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.maps:id/search_omnibox_edit_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '19db6d6b0829f2bcf38754ecee1f8c3101abc49a76b11decf72410800938a7dc'}))
    await action('tap', target='first search result', valid_state='search result is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.maps'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.maps:id/home_bottom_sheet_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 528, 'y': 535})
    await action('scroll', target='location details panel', valid_state='details panel is visible', fixed=True, fixed_values={'direction': 'down', 'pixels': 400})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:reply_to_sms', name='reply_to_sms', description='Reply to the current conversation in the Messages app with a text message.', created_at=1780853330.2784138, success_count=1, success_streak=1)
async def reply_to_sms(device, reply_text):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='text input field', valid_state='input field is visible', fixed=True, fixed_values={'x': 449, 'y': 2246})
    await action('input_text', target='text input field', text=reply_text, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.messaging:id/compose_message_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 981, 'y': 2128})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:send_sms', name='send_sms', description='Send an SMS message to a specified recipient with custom content.', created_at=1780848368.361123, success_count=1, success_streak=1)
async def send_sms(device, recipient_phone, message_content):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='Start chat button', valid_state='chat list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 842, 'y': 2203})
    await action('tap', target='recipient phone number field', valid_state='new conversation screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 378, 'y': 357})
    await action('input_text', target=recipient_phone, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.messaging:id/compose_message_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='recipient suggestion', valid_state='recipient suggestion is visible', fixed=True, fixed_values={'x': 378, 'y': 501})
    await action('input_text', target=message_content, valid_state='message input field is focused')
    await action('tap', target='send button', valid_state='send button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 981, 'y': 2140})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:send_sms_2', name='send_sms_2', description='Send an SMS message to a specified recipient.', created_at=1780853461.3118608, success_count=1, success_streak=1)
async def send_sms_2(device, recipient, message):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('input_text', target=recipient, valid_state='recipient field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.messaging:id/compose_message_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='recipient suggestion', valid_state='recipient suggestion is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='message input field', valid_state='input field is visible')
    await action('input_text', target=message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible', fixed=True, fixed_values={'x': 982, 'y': 2128})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:send_sms_3', name='send_sms_3', description='Send an SMS message to a specified recipient with a given text content.', created_at=1780854114.5302026, success_count=1, success_streak=1)
async def send_sms_3(device, recipient, message):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='Start chat button', valid_state='Start chat button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 842.0, 'y': 2203.0})
    await action('input_text', target='recipient input field', text=recipient, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.messaging:id/compose_message_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='suggested recipient', valid_state='suggested recipient is visible and clickable', fixed=True, fixed_values={'x': 413.0, 'y': 494.0})
    await action('input_text', target='message input field', text=message, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 981.0, 'y': 2138.0})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:send_sms_message', name='send_sms_message', description='Send an SMS message to a contact by entering their phone number and typing the message content.', created_at=1780853217.0481167, success_count=1, success_streak=1)
async def send_sms_message(device, recipient_phone, message_text):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='Start chat button', valid_state='Start chat button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 852, 'y': 2196})
    await action('input_text', target=recipient_phone, valid_state='Recipient input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'com.google.android.apps.messaging:id/compose_message_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '8bf97448dc6b66def31bc1da7e3f4886a66cb4521b8fb7a5a0ca8d7a58e86c04'}))
    await action('tap', target='recipient selection result', valid_state='Recipient selection option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='message composition text field', valid_state='Message input field is visible', fixed=True, fixed_values={'x': 449, 'y': 2136})
    await action('input_text', target=message_text, valid_state='Message input field is focused')
    await action('tap', target='send message button', valid_state='Send button is visible and clickable', fixed=True, fixed_values={'x': 980, 'y': 2128})


@skill(app='com.google.android.apps.messaging', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.apps.messaging:start_new_conversation', name='start_new_conversation', description='Open the messaging app and initiate a new conversation by searching for a contact name.', created_at=1780853402.9680624, success_count=1, success_streak=1)
async def start_new_conversation(device, contact_name):
    await action('open_app', target='com.google.android.apps.messaging', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.apps.messaging'})
    await action('tap', target='Start chat button', valid_state='Start chat button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/group_name_edit_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 843, 'y': 2203})
    await action('tap', target='search input field', valid_state='search field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.apps.messaging'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.apps.messaging:id/home_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 414, 'y': 357})
    await action('input_text', target=contact_name, valid_state='input field is focused')
    await action('enter', target='keyboard enter key', valid_state='search field is focused')


@skill(app='com.google.android.deskclock', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.deskclock:set_alarm', name='set_alarm', description='Opens the Clock app, navigates to the Alarm tab, and sets a new alarm to the specified time.', created_at=1780848754.7974992, success_count=1, success_streak=1)
async def set_alarm(device, alarm_time):
    await action('open_app', target='com.google.android.deskclock', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.deskclock'})
    await action('tap', target='Alarm tab', valid_state='Alarm tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.deskclock'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.deskclock:id/tab_menu_alarm'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 118, 'y': 2220})
    await action('tap', target='Add alarm button', valid_state='Add alarm button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.deskclock'}, 'signature': {'required': [{'selector': {'content_desc': 'Add alarm'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1960})
    await action('input_text', target='time input field', text=alarm_time, valid_state='time input field is focused')
    await action('tap', target='OK button', valid_state='OK button is visible and clickable', fixed=True, fixed_values={'x': 864, 'y': 1821})


@skill(app='com.google.android.dialer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.dialer:navigate_to_contacts', name='navigate_to_contacts', description='Opens the phone application, navigates to the contacts section, and scrolls through the contact list to locate an entry.', created_at=1780837473.2451031, success_count=1, success_streak=1)
async def navigate_to_contacts(device):
    await action('open_app', target='com.google.android.dialer', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.dialer'})
    await action('tap', target='search button', valid_state='search button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.dialer'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.dialer:id/search_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '5c5fa38f86deefb9e21521f590a301216544e4faafcff8eccb8c837faa6f7086'}), fixed=True, fixed_values={'x': 169, 'y': 1970})
    await action('tap', target='contacts tab', valid_state='contacts tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.dialer'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.dialer:id/tab_contacts'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': 'b694939ae5f7978b7e87776c86c9899d14f6b6543be2993c5a400760310e313c'}), fixed=True, fixed_values={'x': 672, 'y': 2239})
    await action('scroll', target='contacts list', valid_state='contacts list is visible and scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:navigate_to_folder', name='navigate_to_folder', description='Navigate to a folder in the Android file picker.', created_at=1780853550.8622124, success_count=1, success_streak=1)
async def navigate_to_folder(device, folder_name):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='menu button', valid_state='menu button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'content_desc': 'Show roots'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 72, 'y': 194})
    await action('tap', target=folder_name, valid_state='folder list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='com.google.android.documentsui', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.documentsui:save_file_to_downloads', name='save_file_to_downloads', description='Saves a file to the Downloads folder with a specified filename.', created_at=1780853882.8548908, success_count=1, success_streak=1)
async def save_file_to_downloads(device, filename):
    await action('open_app', target='com.google.android.documentsui', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.documentsui'})
    await action('tap', target='Save option', valid_state='Save option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 702.0, 'y': 458.0})
    await action('tap', target='breadcrumb navigation', valid_state='breadcrumb navigation is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/collapsing_toolbar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 270.0, 'y': 319.0})
    await action('tap', target='Download folder', valid_state='Download folder is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 756.0, 'y': 909.0})
    await action('tap', target='filename input field', valid_state='filename input field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.documentsui'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.documentsui:id/container_search_fragment'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 486.0, 'y': 2268.0})
    await action('input_text', target=filename, valid_state='input field is focused')


@skill(app='com.google.android.providers.media.module', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.providers.media.module:open_media_picker_and_scroll', name='open_media_picker_and_scroll', description='Opens the system media picker application and scrolls through the recent photos to locate an image.', created_at=1780853522.3538644, success_count=1, success_streak=1)
async def open_media_picker_and_scroll(device):
    await action('open_app', target='com.google.android.providers.media.module', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.providers.media.module'})
    await action('tap', target='Photos tab', valid_state='Photos tab is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.providers.media.module'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.providers.media.module:id/picker_tab_viewpager'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 285, 'y': 1771})
    await action('scroll', target='photo gallery', valid_state='photo gallery is visible', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='com.google.android.providers.media.module', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.providers.media.module:select_image_from_gallery', name='select_image_from_gallery', description="Selects a image from the device's photo gallery to attach to a message.", created_at=1780852963.4671786, success_count=1, success_streak=1)
async def select_image_from_gallery(device, image_description):
    await action('open_app', target='com.google.android.providers.media.module', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.providers.media.module'})
    await action('tap', target='permission allow button', optional=True, valid_state='permission dialog is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.providers.media.module'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.providers.media.module:id/picker_tab_viewpager'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1233})
    await action('tap', target=image_description, valid_state='image is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.providers.media.module'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.providers.media.module:id/picker_tab_viewpager'}, 'state': ['visible', 'enabled', 'scrollable']}], 'forbidden': []}}))


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:confirm_and_send_message', name='confirm_and_send_message', description='Confirm an attached media item and send the message in Mattermost.', created_at=1780853010.8657358, success_count=1, success_streak=1)
async def confirm_and_send_message(device):
    await action('tap', target='Add (1) button', valid_state='file selection dialog is open', fixed=True, fixed_values={'x': 925, 'y': 2241})
    await action('tap', target='send button', valid_state='compose view is active', fixed=True, fixed_values={'x': 952, 'y': 2152})
    await action('done', target='task finished', valid_state='message sent successfully')


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:copy_message_in_channel', name='copy_message_in_channel', description='Locate a message in a Mattermost channel and copy its text content.', created_at=1780851947.9870255, success_count=1, success_streak=1)
async def copy_message_in_channel(device):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='Announcements channel', valid_state='Announcements channel is visible', fixed=True, fixed_values={'x': 313, 'y': 892})
    await action('scroll', target='message list area', valid_state='message list is visible', fixed=True, fixed_values={'direction': 'up', 'pixels': 400})
    await action('long_press', target='security announcement message', valid_state='message is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'class': 'android.view.ViewGroup'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 486, 'y': 568})
    await action('tap', target='Copy Text option', valid_state='context menu is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'content_desc': 'Bottom Sheet'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 249, 'y': 2143})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:create_private_channel', name='create_private_channel', description='Create a new private channel with a specified name.', created_at=1780850007.445288, success_count=1, success_streak=1)
async def create_private_channel(device, channel_name):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='plus button', valid_state='plus button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'text': '\U000f0415'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 991, 'y': 314})
    await action('tap', target='Create New Channel', valid_state='Create New Channel option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'text': 'Create New Channel'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 380, 'y': 2162})
    await action('tap', target='Name input field', valid_state='Name input field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'resource_id': 'channel_info_form.display_name.input'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 528, 'y': 708})
    await action('input_text', target=channel_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'channel_info_form.display_name.input'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '9b558cda05be3b8b0978895d1a3725abc6b3f0f4da61db3344793877deafa0f7'}))
    await action('tap', target='Make Private toggle', valid_state='Make Private toggle is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'resource_id': 'channel_info_form.make_private.toggled.false.button'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 959, 'y': 458})
    await action('tap', target='CREATE button', valid_state='CREATE button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'text': 'CREATE'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 991, 'y': 206})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:open_mattermost_shift_requests_channel', name='open_mattermost_shift_requests_channel', description='Open Mattermost application and navigate to the shift requests channel.', created_at=1780853020.6168196, success_count=1, success_streak=1)
async def open_mattermost_shift_requests_channel(device):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='Shift Requests channel', valid_state='Shift Requests channel is visible in the sidebar', fixed=True, fixed_values={'x': 313, 'y': 1524})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:post_message_in_channel', name='post_message_in_channel', description='Opens Mattermost, navigates to a channel, and posts a message.', created_at=1780852860.31884, success_count=1, success_streak=1)
async def post_message_in_channel(device, channel_name, message_content):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target=channel_name, valid_state='channel list is visible')
    await action('tap', target='message input field', valid_state='input field is visible', fixed=True, fixed_values={'x': 297, 'y': 2172})
    await action('input_text', target=message_content, valid_state='input field is focused')
    await action('tap', target='send button', valid_state='send button is visible', fixed=True, fixed_values={'x': 941, 'y': 2150})


@skill(app='com.mattermost.rnbeta', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.mattermost.rnbeta:start_direct_message', name='start_direct_message', description='In Mattermost, initiate a private direct message conversation with a user.', created_at=1780852923.0795321, success_count=1, success_streak=1)
async def start_direct_message(device, recipient_name):
    await action('open_app', target='com.mattermost.rnbeta', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.mattermost.rnbeta'})
    await action('tap', target='new message button', valid_state='plus button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'text': '\U000f0415'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 992, 'y': 208})
    await action('tap', target='open direct message option', valid_state='menu is open', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'content_desc': 'Bottom Sheet'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 378, 'y': 2284})
    await action('tap', target=recipient_name + ' user entry', valid_state='recipient list is displayed', state_contract=C.from_dict({'anchor': {'app_package': 'com.mattermost.rnbeta'}, 'signature': {'required': [{'selector': {'text': '\U000f0766'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='start conversation button', valid_state='start conversation button is visible', fixed=True, fixed_values={'x': 577, 'y': 2234})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:confirm_deletion_and_scroll', name='confirm_deletion_and_scroll', description='Confirms item deletion in the shopping cart and scrolls through the list to verify removal.', created_at=1780848538.8478634, success_count=1, success_streak=1)
async def confirm_deletion_and_scroll(device):
    await action('tap', target='confirmation dialog OK button', optional=True, valid_state='confirmation dialog is visible', fixed=True, fixed_values={'x': 722.0, 'y': 1365.0})
    await action('scroll', target='shopping cart list', valid_state='cart list is visible', fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:extract_awaiting_shipment_order_details', name='extract_awaiting_shipment_order_details', description='Extracts product names, order numbers, and recipient information from items awaiting shipment in the TaoDian app.', created_at=1780848338.9648197, success_count=1, success_streak=1)
async def extract_awaiting_shipment_order_details(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close popup button', optional=True, valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 484})
    await action('tap', target='profile tab', valid_state='bottom navigation bar is visible', fixed=True, fixed_values={'x': 942, 'y': 2265})
    await action('tap', target='awaiting shipment section', valid_state='order management section is visible', fixed=True, fixed_values={'x': 424, 'y': 952})
    await action('tap', target='first order item', valid_state='order list is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '⏰'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 552})
    await action('done', target='order details page', valid_state='order details are visible')


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:login_via_sms', name='login_via_sms', description='Opens the app, navigates to the cart to trigger login, and switches to SMS login mode.', created_at=1780849149.4194784, success_count=1, success_streak=1)
async def login_via_sms(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='cart icon', valid_state='cart icon is visible', fixed=True, fixed_values={'x': 675.0, 'y': 2263.0})
    await action('tap', target='SMS login tab', valid_state='login screen is visible', fixed=True, fixed_values={'x': 772.0, 'y': 801.0})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:navigate_to_cart', name='navigate_to_cart', description='Open the application and navigate to the shopping cart section.', created_at=1780848400.2683132, success_count=1, success_streak=1)
async def navigate_to_cart(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='shopping cart icon in bottom navigation bar', valid_state='cart icon is visible and clickable', fixed=True, fixed_values={'x': 679.0, 'y': 2272.0})
    await action('tap', target='SMS login button', optional=True, valid_state='login screen is displayed', fixed=True, fixed_values={'x': 775.0, 'y': 804.0})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:navigate_to_orders', name='navigate_to_orders', description='Navigate to the order history page in the shopping application to view past purchases.', created_at=1780848917.1688774, success_count=1, success_streak=1)
async def navigate_to_orders(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button on the promotional popup', optional=True, valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 489})
    await action('tap', target='profile tab at the bottom right', valid_state='profile tab is visible and clickable', fixed=True, fixed_values={'x': 942, 'y': 2270})
    await action('tap', target='all orders option under my orders section', valid_state='all orders option is visible and clickable', fixed=True, fixed_values={'x': 942, 'y': 794})


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:sms_login', name='sms_login', description='Log in to the app using SMS verification code.', created_at=1780848423.008302, success_count=1, success_streak=1)
async def sms_login(device, verification_code):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='OK button on consent popup', optional=True, valid_state='consent popup is visible', fixed=True, fixed_values={'x': 895, 'y': 1372})
    await action('input_text', target='verification code input field', text=verification_code, valid_state='verification code input field is focused')


@skill(app='com.testmall.app', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.testmall.app:view_shopping_cart', name='view_shopping_cart', description='Navigate to the shopping cart and scroll through the item list to view products.', created_at=1780848671.1741035, success_count=1, success_streak=1)
async def view_shopping_cart(device):
    await action('open_app', target='com.testmall.app', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.testmall.app'})
    await action('tap', target='close button', optional=True, valid_state='popup is visible', state_contract=C.from_dict({'anchor': {'app_package': 'com.testmall.app'}, 'signature': {'required': [{'selector': {'text': '×'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 484})
    await action('tap', target='shopping cart icon', valid_state='shopping cart icon is visible', fixed=True, fixed_values={'x': 680, 'y': 2256})
    await action('scroll', target='shopping cart list', direction='down', pixels=400, valid_state='shopping cart list is visible')


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:open_gallery_and_select_image', name='open_gallery_and_select_image', description='Open the gallery app, navigate to an album, and select an image.', created_at=1780848641.055012, success_count=1, success_streak=1)
async def open_gallery_and_select_image(device, album_name, image_description):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target=album_name + ' album', valid_state='album list is visible')
    await action('long_press', target=image_description + ' image', valid_state='image grid is visible', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'class': 'android.widget.RelativeLayout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:select_gallery_photos', name='select_gallery_photos', description='Opens the gallery app, navigates to an album, and selects multiple photos by long-pressing to enter selection mode and tapping the desired images.', created_at=1780853715.7228124, success_count=1, success_streak=1)
async def select_gallery_photos(device, album_name, photo1, photo2):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target=album_name, valid_state='album is visible and clickable')
    await action('long_press', target=photo1, valid_state='image is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'gallery.photomanager.picturegalleryapp.imagegallery'}, 'signature': {'required': [{'selector': {'class': 'android.widget.RelativeLayout'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target=photo1, valid_state='selection mode is active')
    await action('tap', target=photo2, valid_state='selection mode is active')


@skill(app='gallery.photomanager.picturegalleryapp.imagegallery', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:gallery.photomanager.picturegalleryapp.imagegallery:select_image_and_share', name='select_image_and_share', description='Selects a specified image in the gallery and initiates the sharing process.', created_at=1780853744.797174, success_count=1, success_streak=1)
async def select_image_and_share(device, image_description):
    await action('open_app', target='gallery.photomanager.picturegalleryapp.imagegallery', valid_state='No need to verify', fixed=True, fixed_values={'text': 'gallery.photomanager.picturegalleryapp.imagegallery'})
    await action('tap', target=image_description, valid_state='image is visible')
    await action('tap', target='share button', valid_state='share button is visible', fixed=True, fixed_values={'x': 793, 'y': 208})


@skill(app='mcurrentfocus-window-5ccb194-u0-media-viewer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-5ccb194-u0-media-viewer:favorite_post', name='favorite_post', description='Favorites a post in the Mastodon application.', created_at=1780849940.0790048, success_count=1, success_streak=1)
async def favorite_post(device):
    await action('open_app', target='mcurrentfocus-window-5ccb194-u0-media-viewer', valid_state='No need to verify', fixed=True, fixed_values={'text': 'mcurrentfocus-window-5ccb194-u0-media-viewer'})
    await action('tap', target='bottom navigation bar', valid_state='bottom bar is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-5ccb194-u0-media-viewer'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/bottom_bar'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 572, 'y': 2126})
    await action('tap', target='favorite button', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-5ccb194-u0-media-viewer'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 444, 'y': 2265})


@skill(app='mcurrentfocus-window-8faa1d0-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-8faa1d0-u0-dropdown-menu:navigate_to_lists_mastodon', name='navigate_to_lists_mastodon', description='Navigate to the Lists feature in Mastodon via the navigation drawer.', created_at=1780850083.0798602, success_count=1, success_streak=1)
async def navigate_to_lists_mastodon(device):
    await action('tap', target='hamburger menu', valid_state='hamburger menu is visible', fixed=True, fixed_values={'x': 91.0, 'y': 199.0})
    await action('tap', target='Lists menu item', valid_state='Lists option is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-8faa1d0-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Lists'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 162.0, 'y': 712.0})


@skill(app='mcurrentfocus-window-9c1df19-u0-dropdown-menu', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:mcurrentfocus-window-9c1df19-u0-dropdown-menu:navigate_to_lists', name='navigate_to_lists', description='Navigate to the Lists section in Mastodon', created_at=1780851236.433366, success_count=1, success_streak=1)
async def navigate_to_lists(device):
    await action('tap', target='navigation toggle button', valid_state='navigation toggle is visible', fixed=True, fixed_values={'x': 91.0, 'y': 196.0})
    await action('tap', target='Lists menu item', valid_state='Lists option is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'mcurrentfocus-window-9c1df19-u0-dropdown-menu'}, 'signature': {'required': [{'selector': {'text': 'Lists'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 248.0, 'y': 708.0})


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:check_calendar_conflict', name='check_calendar_conflict', description='Open the Fossify Calendar application, navigate to a date to view scheduled events, and return to the home screen.', created_at=1780853281.3482127, success_count=1, success_streak=1)
async def check_calendar_conflict(device):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='October 20', valid_state='October 20 is visible and clickable', fixed=True, fixed_values={'x': 226.0, 'y': 1524.0})
    await action('back', target='calendar month view', valid_state='calendar month view is visible')
    await action('back', target='home screen', valid_state='home screen is visible')


@skill(app='org.fossify.calendar', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.fossify.calendar:open_calendar_app', name='open_calendar_app', description='Open the Fossify Calendar app and navigate to the month view.', created_at=1780853081.9951274, success_count=1, success_streak=1)
async def open_calendar_app(device):
    await action('open_app', target='org.fossify.calendar', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.fossify.calendar'})
    await action('tap', target='calendar header', valid_state='header is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.fossify.calendar'}, 'signature': {'required': [{'selector': {'resource_id': 'org.fossify.calendar:id/top_value'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 364})
    await action('tap', target='confirm button', valid_state='button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.fossify.calendar'}, 'signature': {'required': [{'selector': {'resource_id': 'org.fossify.calendar:id/date_picker'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 841, 'y': 1512})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:bookmark_post', name='bookmark_post', description='Bookmark posts with hashtags on a Mastodon user profile.', created_at=1780846972.2818851, success_count=1, success_streak=1)
async def bookmark_post(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Bookmark option in post menu', valid_state='Bookmark option is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Header image'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '2fb898fb959fe24643a1e0983afe9f2a78d6f2c79f2d4cd21a7f515fb75b2d71'}), fixed=True, fixed_values={'x': 702, 'y': 300})
    await action('scroll', target='post timeline', direction='down', pixels=400, valid_state='Timeline is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:compose_post', name='compose_post', description='Compose a new post with specified content in Mastodon.', created_at=1780851976.2326794, success_count=1, success_streak=1)
async def compose_post(device, content):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='compose button', valid_state='compose button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'New post'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 972.0, 'y': 2008.0})
    await action('input_text', target=content, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:compose_post_2', name='compose_post_2', description='Compose and post a message with visibility and mentions in Mastodon.', created_at=1780852538.4589908, success_count=1, success_streak=1)
async def compose_post_2(device, content):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='compose button', valid_state='compose button is visible and clickable', fixed=True, fixed_values={'x': 950, 'y': 1700})
    await action('tap', target='visibility dropdown', valid_state='visibility dropdown is visible', fixed=True, fixed_values={'x': 259, 'y': 1000})
    await action('input_text', target=content, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))
    await action('tap', target='publish button', valid_state='publish button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Publish'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1015, 'y': 204})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:create_list', name='create_list', description='Create a new Mastodon list with a specified name.', created_at=1780850134.3166232, success_count=1, success_streak=1)
async def create_list(device, list_name):
    await action('tap', target='Create list option', valid_state='Create list option is visible', fixed=True, fixed_values={'x': 199.0, 'y': 909.0})
    await action('tap', target='List name input field', valid_state='List name input field is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 216.0, 'y': 381.0})
    await action('input_text', target=list_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:create_mastodon_list', name='create_mastodon_list', description='Create a new Mastodon list with a specified name.', created_at=1780851807.7552426, success_count=1, success_streak=1)
async def create_mastodon_list(device, list_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Manage lists', valid_state='Manage lists option is visible and clickable', fixed=True, fixed_values={'x': 248.0, 'y': 1053.0})
    await action('tap', target='Create list button', valid_state='Create list button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Create list'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 972.0, 'y': 2181.0})
    await action('tap', target='List name input field', valid_state='List name input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 248.0, 'y': 381.0})
    await action('input_text', target=list_name, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:create_mastodon_list_2', name='create_mastodon_list_2', description='Creates a new list in Mastodon with a specified name and hides members in following.', created_at=1780851889.1007185, success_count=1, success_streak=1)
async def create_mastodon_list_2(device, list_name):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Create list floating action button', valid_state='Create list button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Create list'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 972.0, 'y': 2181.0})
    await action('tap', target='List name input field', valid_state='Input field is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 248.0, 'y': 381.0})
    await action('input_text', target=list_name, valid_state='Input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/edit'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '28f96ad2adbcc4e7db57b3454686a7d04f81184cda1a2851695036b53159d333'}))
    await action('tap', target='Hide members in Following toggle', valid_state='Toggle is visible and clickable', fixed=True, fixed_values={'x': 972.0, 'y': 756.0})
    await action('tap', target='Create button', valid_state='Create button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/btn_next'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540.0, 'y': 2143.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:edit_profile_header', name='edit_profile_header', description='Navigate to the profile page and open the profile editing interface to change the header image.', created_at=1780849828.6090121, success_count=1, success_streak=1)
async def edit_profile_header(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab in bottom navigation bar', valid_state='Profile tab is visible and clickable', fixed=True, fixed_values={'x': 950.0, 'y': 2220.0})
    await action('tap', target='Edit profile button', valid_state='Edit profile button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 476.0, 'y': 1065.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:favorite_hashtag_posts', name='favorite_hashtag_posts', description='Favorites posts containing a hashtag in Mastodon.', created_at=1780849908.8415606, success_count=1, success_streak=1)
async def favorite_hashtag_posts(device, hashtag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore icon in bottom navigation bar', valid_state='Explore icon is visible', fixed=True, fixed_values={'x': 407.0, 'y': 2220.0})
    await action('tap', target='search input field', valid_state='search field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 347.0, 'y': 249.0})
    await action('input_text', target=hashtag, valid_state='input field is focused')
    await action('tap', target="Posts with '" + hashtag + "' search result", valid_state='search result list is visible', fixed=True, fixed_values={'x': 356.0, 'y': 427.0})
    await action('tap', target='favorite button (star icon)', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 572.0, 'y': 2126.0})
    await action('scroll', target='feed content', valid_state='posts are visible', fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:favorite_hashtag_posts_2', name='favorite_hashtag_posts_2', description='Favorites posts associated with a hashtag in Mastodon by scrolling through the feed and tapping the favorite button.', created_at=1780849981.5180173, success_count=1, success_streak=1)
async def favorite_hashtag_posts_2(device, hashtag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='search icon', valid_state='search icon is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('input_text', target='search input field', text=hashtag, valid_state='search input field is focused')
    await action('enter', target='search input field', valid_state='search input field is focused')
    await action('scroll', target='feed', valid_state='feed is scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})
    await action('tap', target='favorite button', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:favorite_post', name='favorite_post', description='Favorites the currently displayed post in Mastodon by tapping the star icon.', created_at=1780850900.3897398, success_count=1, success_streak=1)
async def favorite_post_2(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='favorite button', valid_state='favorite button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}))
    await action('back', target='back button', valid_state='feed is visible')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_following_list', name='navigate_to_following_list', description='Navigate to the following list in the Mastodon app.', created_at=1780852788.058235, success_count=1, success_streak=1)
async def navigate_to_following_list(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='profile icon', valid_state='profile icon is visible and clickable', fixed=True, fixed_values={'x': 950.0, 'y': 2220.0})
    await action('tap', target='following link', valid_state='following link is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/following_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 378.0, 'y': 960.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:navigate_to_mastodon_profile_and_explore', name='navigate_to_mastodon_profile_and_explore', description='Open the Mastodon app and navigate to the Profile and Explore sections to locate the Lists feature.', created_at=1780850055.410962, success_count=1, success_streak=1)
async def navigate_to_mastodon_profile_and_explore(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Profile tab', valid_state='Profile tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/tab_profile_ava'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 950.0, 'y': 2208.0})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible and clickable', fixed=True, fixed_values={'x': 405.0, 'y': 2208.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_mastodon_and_retry', name='open_mastodon_and_retry', description='Open the Mastodon application and handle connection errors by retrying.', created_at=1780852811.7180996, success_count=1, success_streak=1)
async def open_mastodon_and_retry(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Retry button', optional=True, valid_state='connection error screen is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'text': 'Retry'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1327})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:open_settings', name='open_settings', description='Opens the Mastodon application and navigates to the main settings menu.', created_at=1780850911.3418238, success_count=1, success_streak=1)
async def open_settings(device):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='settings button', valid_state='settings button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/settings'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 915, 'y': 199})
    await action('scroll', target='settings list', text='down', pixels=400, valid_state='settings list is scrollable')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:post_toot', name='post_toot', description='Post a new message to Mastodon.', created_at=1780852557.5885491, success_count=1, success_streak=1)
async def post_toot(device, message):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='New post button', valid_state='compose button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'New post'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 961, 'y': 1992})
    await action('input_text', target=message, valid_state='input field is focused', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'class': 'android.widget.EditText', 'resource_id': 'org.joinmastodon.android.mastodon:id/toot_text'}, 'state': ['visible', 'enabled', 'focused']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '879f56728334dff2069d5649bb4b439037071fa74aeaaa2f215fa106082bd2e4'}))
    await action('tap', target='publish button', valid_state='publish button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Publish'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1015, 'y': 201})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_and_favorite_tag', name='search_and_favorite_tag', description='Search for a hashtag in Mastodon and favorite the first post.', created_at=1780850854.5103655, success_count=1, success_streak=1)
async def search_and_favorite_tag(device, tag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 407, 'y': 2215})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 347, 'y': 247})
    await action('input_text', target=tag, valid_state='input field is focused')
    await action('tap', target='hashtag search result', valid_state='search result is visible', fixed=True, fixed_values={'x': 356, 'y': 427})
    await action('tap', target='favorite button', valid_state='favorite button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/favorite_btn'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 572, 'y': 2126})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_and_follow_mastodon_user', name='search_and_follow_mastodon_user', description='Search for a user by their nickname or handle on Mastodon and follow their profile.', created_at=1780837510.791751, success_count=1, success_streak=1)
async def search_and_follow_mastodon_user(device, nickname):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab in bottom navigation bar', valid_state='bottom navigation bar is visible', fixed=True, fixed_values={'x': 407.0, 'y': 2217.0})
    await action('tap', target='search input field', valid_state='search field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '83e09e4b5b1fc3aca65dcd9dcee808db1be7ba9c3db1eea4c5991ae7e288a8a7'}), fixed=True, fixed_values={'x': 300.0, 'y': 240.0})
    await action('input_text', target=nickname, valid_state='input field is focused')
    await action('tap', target='matching profile result', valid_state='profile result is visible and clickable')
    await action('tap', target='follow button', valid_state='follow button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '839fcd75ef66342e07f4a0bf04cdf5425116658a616848202ce92ec1d6e15c96'}), fixed=True, fixed_values={'x': 486.0, 'y': 984.0})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_hashtag', name='search_hashtag', description='Search Mastodon for a hashtag and browse the posts feed.', created_at=1780850243.2645533, success_count=1, success_streak=1)
async def search_hashtag(device, query):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='search bar', valid_state='search bar is visible', fixed=True, fixed_values={'x': 486, 'y': 244})
    await action('tap', target='clear button', valid_state='clear button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'content_desc': 'Clear'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 1013, 'y': 240})
    await action('input_text', target=query, valid_state='input field is focused')
    await action('tap', target='posts search result', valid_state='search suggestions are visible', fixed=True, fixed_values={'x': 378, 'y': 420})
    await action('scroll', target='feed', valid_state='feed is loaded', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_mastodon_posts', name='search_mastodon_posts', description='Search Mastodon for posts using a query.', created_at=1780850217.596991, success_count=1, success_streak=1)
async def search_mastodon_posts(device, query):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible', fixed=True, fixed_values={'x': 403.0, 'y': 2241.0})
    await action('tap', target='search bar', valid_state='search bar is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 361.0, 'y': 249.0})
    await action('input_text', target=query, valid_state='search field is focused')
    await action('tap', target='search result for posts', valid_state='search results are displayed')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_posts_by_user_and_hashtag', name='search_posts_by_user_and_hashtag', description='In Mastodon, search for posts by a user containing a hashtag.', created_at=1780846880.5437229, success_count=1, success_streak=1)
async def search_posts_by_user_and_hashtag(device, username, hashtag):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible and clickable', fixed=True, fixed_values={'x': 402, 'y': 2229})
    await action('tap', target='Search bar', valid_state='Search bar is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}, 'mask_rules': [], 'fingerprint': '83e09e4b5b1fc3aca65dcd9dcee808db1be7ba9c3db1eea4c5991ae7e288a8a7'}), fixed=True, fixed_values={'x': 347, 'y': 249})
    await action('input_text', target=username + ' ' + hashtag, valid_state='Search input field is focused')
    await action('tap', target="Posts with '" + username + ' ' + hashtag + "'", valid_state='Search result list item is visible and clickable')


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_user_profile', name='search_user_profile', description='Search for a user by username and navigate to their profile in Mastodon.', created_at=1780851121.0703084, success_count=1, success_streak=1)
async def search_user_profile(device, username):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab', valid_state='Explore tab is visible and clickable', fixed=True, fixed_values={'x': 403, 'y': 2241})
    await action('tap', target='search bar', valid_state='search bar is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 234, 'y': 201})
    await action('input_text', target=username, valid_state='input field is focused')
    await action('tap', target='user profile result', valid_state='user profile result is visible and clickable', fixed=True, fixed_values={'x': 248, 'y': 998})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:update_profile_header', name='update_profile_header', description='Update the Mastodon profile header image.', created_at=1780849879.8917508, success_count=1, success_streak=1)
async def update_profile_header(device, media_item):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target=media_item, valid_state='profile header area is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_about'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}))
    await action('tap', target='save changes button', valid_state='save changes button is visible', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_actions'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 540, 'y': 1274})
