from opengui.skills.flat import C, R, action, skill, tag


@skill(app='com.google.android.dialer', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.google.android.dialer:navigate_to_contacts', name='navigate_to_contacts', description='Opens the phone application, navigates to the contacts section, and scrolls through the contact list to locate an entry.', created_at=1780837473.2451031, success_count=1, success_streak=1)
async def navigate_to_contacts(device):
    await action('open_app', target='com.google.android.dialer', valid_state='No need to verify', fixed=True, fixed_values={'text': 'com.google.android.dialer'})
    await action('tap', target='search button', valid_state='search button is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.dialer'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.dialer:id/search_fragment_container'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 169, 'y': 1970})
    await action('tap', target='contacts tab', valid_state='contacts tab is visible and clickable', state_contract=C.from_dict({'anchor': {'app_package': 'com.google.android.dialer'}, 'signature': {'required': [{'selector': {'resource_id': 'com.google.android.dialer:id/tab_contacts'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 672, 'y': 2239})
    await action('scroll', target='contacts list', valid_state='contacts list is visible and scrollable', fixed=True, fixed_values={'pixels': 400, 'direction': 'down'})


@skill(app='org.joinmastodon.android.mastodon', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:org.joinmastodon.android.mastodon:search_and_follow_mastodon_user', name='search_and_follow_mastodon_user', description='Search for a user by their nickname or handle on Mastodon and follow their profile.', created_at=1780837510.791751, success_count=1, success_streak=1)
async def search_and_follow_mastodon_user(device, nickname):
    await action('open_app', target='org.joinmastodon.android.mastodon', valid_state='No need to verify', fixed=True, fixed_values={'text': 'org.joinmastodon.android.mastodon'})
    await action('tap', target='Explore tab in bottom navigation bar', valid_state='bottom navigation bar is visible', fixed=True, fixed_values={'x': 407.0, 'y': 2217.0})
    await action('tap', target='search input field', valid_state='search field is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/search_text'}, 'state': ['visible', 'clickable', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 300.0, 'y': 240.0})
    await action('input_text', target=nickname, valid_state='input field is focused')
    await action('tap', target='matching profile result', valid_state='profile result is visible and clickable')
    await action('tap', target='follow button', valid_state='follow button is visible and enabled', state_contract=C.from_dict({'anchor': {'app_package': 'org.joinmastodon.android.mastodon'}, 'signature': {'required': [{'selector': {'resource_id': 'org.joinmastodon.android.mastodon:id/profile_action_btn_wrap'}, 'state': ['visible', 'enabled']}], 'forbidden': []}}), fixed=True, fixed_values={'x': 486.0, 'y': 984.0})
