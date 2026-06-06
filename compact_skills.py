from opengui.skills.flat import C, R, action, skill, tag


@skill(app='com.gmailclone', platform='android', tags=['compact', 'compact_extracted'], skill_id='compact:com.gmailclone:fill_email_recipient_and_subject', name='fill_email_recipient_and_subject', description='When to use: To quickly populate the recipient and subject fields on the email composition screen.', created_at=1780714355.3378255)
async def fill_email_recipient_and_subject(device, to_email, subject):
    await action('tap', target='To', valid_state='No need to verify')
    await action('input_text', target=to_email, valid_state='No need to verify')
    await action('tap', target='Subject', valid_state='No need to verify')
    await action('input_text', target=subject, valid_state='No need to verify')

