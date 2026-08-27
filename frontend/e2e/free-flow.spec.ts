import { expect, test } from '@playwright/test'

const apiBaseURL = `http://127.0.0.1:${process.env.E2E_API_PORT || '8002'}`
const expectedTaskBackend = process.env.E2E_TASK_QUEUE_BACKEND || 'local'

test('free user can complete resume to report delivery flow', async ({ page }) => {
  test.setTimeout(180_000)
  const email = `free-flow-${Date.now()}@example.com`
  const answer =
    '我会先说明项目背景和个人边界，再拆解接口、数据、检索和任务队列链路。实现上用 FastAPI 提供接口，Redis/RQ 处理长任务，Qdrant 存储证据向量，并通过日志和测试验证优化结果。'

  await test.step('register and upload sample resume', async () => {
    await page.goto('/login')
    await page.getByRole('button', { name: '没有账号，创建一个' }).click()
    await page.getByLabel('邮箱').fill(email)
    await page.getByLabel('密码').fill('password123')
    await page.getByLabel('昵称').fill('Free Flow')
    await page.getByRole('button', { name: '注册并登录' }).click()

    await expect(page.getByRole('heading', { name: '求职训练工作台' })).toBeVisible()
    await page.getByTestId('fill-sample-resume-button').click()
    await page.getByTestId('upload-resume-button').click()
    await expect(page.getByRole('heading', { name: '示例简历 - AI Agent 应用开发' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('resume-evidence-index-card')).toContainText('片')
  })

  let jobUrl = ''
  await test.step('create job and run JD resume optimization task', async () => {
    await page.goto('/jobs')
    await expect(page.getByRole('heading', { name: '岗位工作台' })).toBeVisible()
    await page.getByTestId('fill-sample-job-button').click()
    await page.getByTestId('create-job-button').click()
    await expect(page.getByTestId('job-card').first()).toContainText('AI Agent 应用开发实习生')
    await page.getByTestId('job-card').first().getByRole('button', { name: '打开详情' }).click()

    await expect(page.getByRole('heading', { name: /AI Agent 应用开发实习生/ })).toBeVisible()
    await page.getByTestId('job-adapt-button').click()
    await expect(page.getByText('岗位简历优化已完成')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ats-panel')).toBeVisible()
    const token = await page.evaluate(() => window.localStorage.getItem('token'))
    const tasks = await page.request.get(`${apiBaseURL}/api/tasks`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(tasks.ok()).toBeTruthy()
    const taskPayload = await tasks.json()
    const jobTask = taskPayload.find((task: { task_type: string }) => task.task_type === 'job.adapt_resume')
    expect(jobTask?.queue_backend).toBe(expectedTaskBackend === 'redis_rq' ? 'redis_rq' : 'local')
    jobUrl = page.url()
  })

  await test.step('verify before and after diff and export delivery resume', async () => {
    await page.getByRole('tab', { name: /投递准备/ }).click()
    const resumeDownload = page.waitForEvent('download')
    await page.getByTestId('export-delivery-resume-button').click()
    const resumeFile = await resumeDownload
    expect(resumeFile.suggestedFilename()).toMatch(/投递版简历\.docx$/)

    await page.getByRole('button', { name: '简历版本' }).click()
    await page.getByRole('button', { name: '优化结果' }).click()
    await expect(page.getByTestId('change-details-panel')).toBeVisible()
    await expect(page.getByTestId('change-details-panel')).toContainText('修改后')
    await page.goto(jobUrl)
    await page.getByRole('tab', { name: /投递准备/ }).click()
    await expect(page.getByTestId('submit-quality-feedback-button')).toHaveCount(0)
    await expect(page.getByText('质量反馈已记录')).toHaveCount(0)
  })

  await test.step('generate interview questions, answer three, and finish report', async () => {
    await page.goto(jobUrl)
    await page.getByRole('tab', { name: /投递准备/ }).click()
    await page.getByTestId('start-job-interview-button').click()
    await expect(page.getByRole('heading', { name: '模拟面试' })).toBeVisible({ timeout: 90_000 })
    if (await page.getByText('题库尚未生成').isVisible()) {
      await page.getByRole('button', { name: '生成面试题目' }).click()
    }
    await expect(page.getByTestId('question-navigation')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('question-navigation')).toContainText('项目深挖')
    await expect(page.getByTestId('question-navigation')).toContainText('实习经历')
    await expect(page.getByTestId('question-navigation')).toContainText('Agent 八股')
    await expect(page.getByTestId('question-evidence-panel')).toBeVisible()

    for (let index = 0; index < 3; index += 1) {
      await page.getByTestId('answer-textarea').fill(`${answer} 当前回答序号 ${index + 1}。`)
      await page.getByTestId('submit-answer-button').click()
      await expect(page.getByText('评分与参考答案')).toBeVisible({ timeout: 60_000 })
      if (index < 2) {
        await page.getByTestId('next-question-button').click()
      }
    }

    await page.getByTestId('finish-interview-button').click()
    await expect(page.getByTestId('report-page')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '面试总结报告' })).toBeVisible()
    await expect(page.getByTestId('report-details-panel')).toBeVisible()
  })

  await test.step('export interview report Word and PDF', async () => {
    const docxDownload = page.waitForEvent('download')
    await page.getByTestId('export-report-docx-button').click()
    const docxFile = await docxDownload
    expect(docxFile.suggestedFilename()).toMatch(/\.docx$/)

    const pdfDownload = page.waitForEvent('download')
    await page.getByTestId('export-report-pdf-button').click()
    const pdfFile = await pdfDownload
    expect(pdfFile.suggestedFilename()).toMatch(/\.pdf$/)
  })
})
