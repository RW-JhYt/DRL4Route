# -*- coding: utf-8 -*-
import os
os.environ["CUDA_VISIBLE_DEVICES"] = '0,1,2,3'
from my_utils.utils import *
from algorithm.DRL4Route.Dataset import DRL4RouteDataset

def test_model(model, test_dataloader, device, pad_value, params, save2file, mode):
    from my_utils.eval import Metric
    model.eval()

    evaluator_1 = Metric([1, 5])
    evaluator_2 = Metric([1, 11])
    evaluator_3 = Metric([1, 15])
    evaluator_4 = Metric([1, 25])
    with torch.no_grad():

        for batch in tqdm(test_dataloader):
            batch = to_device(batch, device)
            V, V_reach_mask, label, label_len = batch
            outputs, pointers, _ = model(V, V_reach_mask, sample = False, type = 'mle')

            pred_steps, label_steps, labels_len = \
                get_nonzeros(pointers.reshape(-1, outputs.size()[-1]), label.reshape(-1, outputs.size()[-1]),
                             label_len.reshape(-1), pad_value)

            evaluator_1.update(pred_steps, label_steps, labels_len)
            evaluator_2.update(pred_steps, label_steps, labels_len)
            evaluator_3.update(pred_steps, label_steps, labels_len)
            evaluator_4.update(pred_steps, label_steps, labels_len)

    if mode == 'val':
        return evaluator_4

    params_1 = dict_merge([evaluator_1.to_dict(), params])
    params_1['eval_min'] = 1
    params_1['eval_max'] = 5
    save2file(params_1)

    print(evaluator_2.to_str())
    params_2 = dict_merge([evaluator_2.to_dict(), params])
    params_2['eval_min'] = 1
    params_2['eval_max'] = 11
    save2file(params_2)

    print(evaluator_3.to_str())
    params_3 = dict_merge([evaluator_3.to_dict(), params])
    params_3['eval_min'] = 1
    params_3['eval_max'] = 15
    save2file(params_3)

    print(evaluator_4.to_str())
    params_4 = dict_merge([evaluator_4.to_dict(), params])
    params_4['eval_min'] = 1
    params_4['eval_max'] = 25
    save2file(params_4)

    return evaluator_4

def process_batch(batch, model, device, params):
    batch = to_device(batch, device)
    V, V_reach_mask, label, label_len = batch

    pred_scores, pred_pointers, values = model(V, V_reach_mask, sample=False, type='mle')
    unrolled = pred_scores.view(-1, pred_scores.size(-1))
    N = pred_pointers.size(-1)
    mle_loss = F.cross_entropy(unrolled, label.view(-1), ignore_index=params['pad_value'])
    rl_log_probs, sample_out, sample_values = model(V, V_reach_mask, sample=True, type='rl')
    with torch.autograd.no_grad():
        _, greedy_out, _ = model(V, V_reach_mask, sample=False, type='rl')
    if params['model'] == 'DRL4Route_REINFORCE':
        seq_pred_len = torch.sum((pred_pointers.reshape(-1, N) < N - 1) + 0, dim=1)
        seq_pred_len = seq_pred_len.masked_fill(seq_pred_len == 0, 1)
        rl_log_probs = torch.sum(rl_log_probs, dim=1) / seq_pred_len

        sample_out_samples, label_samples, label_len_samples, rl_log_probs_samples = \
            get_reinforce_sample(sample_out.reshape(-1, N), label.reshape(-1, N), label_len.reshape(-1), params['pad_value'], rl_log_probs)
        krc_reward, lsd_reward, acc_3_reward = calc_reinforce_rewards(sample_out_samples, label_samples, label_len_samples, params)
        reinforce_loss = -torch.mean(torch.tensor(lsd_reward).to(rl_log_probs_samples.device) * rl_log_probs_samples)  # 希望sample_lsd越小越好
        loss = mle_loss + params['rl_ratio'] * reinforce_loss
    else:
        loss = mle_loss

    return pred_pointers, pred_scores, loss, sample_out, greedy_out, label, V_reach_mask, rl_log_probs, sample_values

def main(params):
    trainer = DRL4Route()
    trainer.run(params, DRL4RouteDataset, process_batch, test_model)

def get_params():
    parser = get_common_params()
    args, _ = parser.parse_known_args()
    return args

if __name__ == '__main__':
    import time, nni
    import logging

    logger = logging.getLogger('training')
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    print('GPU:', torch.cuda.current_device())
    try:
        tuner_params = nni.get_next_parameter()
        logger.debug(tuner_params)
        params = vars(get_params())
        params.update(tuner_params)
        main(params)
    except Exception as exception:
        logger.exception(exception)
        raise
