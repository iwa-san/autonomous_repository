import os
import sys
import datetime
print("ライブラリの初期化に数秒かかります...")
import pandas as pd
import torch
from torch import nn
import torch.nn.functional as F
from torch.utils.data import DataLoader #, TensorDataset
import matplotlib.pyplot as plt

import config

# データの読み込みと前処理
def load_data():
    folder = "records"
    csv_files = []
    for file in os.listdir(folder):
        if file.endswith(".csv"):
            csv_files.append(file)
    print(csv_files)

    if len(csv_files) > 1:
        answer = input("\n複数のcsvファイルがあります。ファイルを結合しますか？ (y)")
        if answer == "y":
            dataframes = []
            dataframe_colums = []
            for csv_file in csv_files:
                csv_path = os.path.join(folder, csv_file)
                df = pd.read_csv(csv_path)
                dataframes.append(df)
                dataframe_colums.append(df.columns)
                if len(dataframe_colums) > 1:
                    if not all(dataframe_colums[0] == dataframe_colums[1]):
                        print(csv_path, "の列が他のファイルと異なり結合できません。確認してください。")
                        sys.exit()
                merged_df = pd.concat(dataframes)
            df = merged_df
        else:
            csv_file = input("csvファイル名を入力してください: ")
            #csv_file = "record_20240519_224821.csv"
            csv_path = os.path.join(folder, csv_file)
            df = pd.read_csv(csv_path)
    else:
        csv_file = csv_files[0]
        csv_path = os.path.join(folder, csv_file)
        df = pd.read_csv(csv_path)
    #print("\n入力データのヘッダー確認:\n", df.columns)
    print("\n入力データの確認:\n", df.head(3), "\nデータサイズ",df.shape)
    x = df.iloc[:, 3:]
    y = df.iloc[:, 1:3]
    x_tensor = torch.tensor(x.values, dtype=torch.float32)
    x_tensor = normalize_ultrasonics(x_tensor)
    y_tensor = torch.tensor(y.values, dtype=torch.float32)
    y_tensor = normalize_motor(y_tensor)
    y_tensor[:, 0] = steering_shifter_to_01(y_tensor[:, 0])  # ステアリングの値を-1~1を0~1に変換
    
    #y_tensor = steering_shifter_to_01(y_tensor) # -1~1を0~1に変換
    print("\n学習データの確認:\n教師データ(正規化操作値+0.5, Str, Thr):", y_tensor[0,:], "\n入力データ(正規化センサ値)", x_tensor[0,:])
    print("学習データサイズ:", "y:", y_tensor.shape, "x:", x_tensor.shape, "\n")
    return x_tensor, y_tensor, csv_file

def normalize_ultrasonics(x_tensor, scale=2000):
    x_tensor = x_tensor / scale # 2000mmを1として正規化
    return x_tensor

def denormalize_ultrasonics(x_tensor, scale=2000):
    x_tensor = x_tensor * scale # 2000mmを1として正規化
    return x_tensor

def normalize_motor(y_tensor, scale=100):
    y_tensor = y_tensor / scale # 100%を1として正規化
    return y_tensor

def denormalize_motor(y_tensor, scale=100):
    y_tensor = y_tensor * scale # 100%を1として正規化
    return y_tensor

# -1~1を0~1に変換
def steering_shifter_to_01(y_tensor):
    y_tensor = (y_tensor +1 )/2
    return y_tensor

# 0~1を-1~1に変換
def steering_shifter_to_m11(y_tensor):
    y_tensor = (y_tensor-0.5)*2
    return y_tensor

# カスタムデータセットクラス
class CustomDataset(torch.utils.data.Dataset):
    def __init__(self, x_tensor, y_tensor):
        self.x = x_tensor
        self.y = y_tensor

    def __len__(self):
        return len(self.x)

    def __getitem__(self, idx):
        return self.x[idx], self.y[idx]

# モデルの定義
class NeuralNetwork(nn.Module):
    def __init__(self, input_dim, output_dim,hidden_dim, num_hidden_layers):
        super(NeuralNetwork, self).__init__()
        ## 変数で層を追加
        layers = []
        layers.append(nn.Linear(input_dim, hidden_dim))
        layers.append(nn.ReLU())

        for _ in range(num_hidden_layers - 1):
                    layers.append(nn.Linear(hidden_dim, hidden_dim))
                    layers.append(nn.ReLU())

        layers.append(nn.Linear(hidden_dim, output_dim))

        self.layers = nn.Sequential(*layers)

        # 手動で層を追加
        #self.layers = nn.Sequential(
        #    nn.Linear(input_dim, 64),
        #    nn.ReLU(),
        #    nn.Linear(64, 64),
        #    nn.ReLU(),
        #    nn.Linear(64, output_dim)
        #)

    def forward(self, x):
        x = self.layers(x)
        return x

    # 推論関数
    def predict(self, model, x_tensor):
        #x_tensor = normalize_ultrasonics(x_tensor)
        model.eval()  # モデルを評価モードに設定
        with torch.no_grad():
            predictions = model(x_tensor)
            #predictions = F.softmax(predictions, dim=1)
        predictions[:,0] = steering_shifter_to_m11(predictions[:,0]) # 0~1を-1~1に変換
        predictions = torch.clamp(predictions, min=-1, max=1)  # Clamp values between -1 and 1
        #predictions = denormalize_motor(predictions)
        return predictions

# トレーニング関数
def train_model(model, dataloader, criterion, optimizer, start_epoch=0, epochs=100):
    model.train()  # モデルをトレーニングモードに設定
    loss_history = []  # Loss values for plotting
    for epoch in range(start_epoch, start_epoch + epochs):
        for inputs, targets in dataloader:
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()
        loss_history.append(loss.item())  # Record the loss value
        print(f'Epoch {epoch+1}/{epochs}, Loss: {loss.item()}')
    print("トレーニングが完了しました。")
    
    # Plot and save the loss values
    plt.figure()
    plt.plot(loss_history, label='Loss')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()
    loss_history_path = config.model_dir+'/'+'loss_history.png'
    plt.savefig(loss_history_path)
    plt.close()
    print("Lossの履歴を保存しました: "+loss_history_path)
    return epoch+1
    

# モデル保存関数
def save_model(model, optimizer, folder, csv_file, epoch):
    if not os.path.exists(folder):
        os.makedirs(folder)
    date_str = datetime.datetime.now().strftime('%Y%m%d')
    model_name = f'model_{date_str}_{csv_file}_epoch_{epoch}_{config.ultrasonics_list_join}.pth'
    model_path = os.path.join(folder, model_name)
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict()
    }, model_path)
    print(f"モデルを保存しました: {model_name}")
    return model_path


def load_model(model, model_path=None,optimizer=None, folder='.'):
    """
    モデルを指定したフォルダーから読み込む関数。
    
    Args:
    - model: PyTorchモデルのインスタンス
    - optimizer: PyTorchのoptimizerのインスタンス（省略可能）
    - folder: モデルファイルが保存されているフォルダー

    Returns:
    - epoch: 読み込んだモデルのエポック数（失敗時は0）
    """
    if model_path:
        checkpoint = torch.load(model_path)
        model.load_state_dict(checkpoint['model_state_dict'])
        if optimizer:
            optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            print("オプティマイザの状態も読み込みました。")
        print(f"モデルを読み込みました: {model_path}")
        return checkpoint.get('epoch', 0)
    else:
        model_files = [file for file in os.listdir(folder) if file.startswith('model_')]
        if model_files:
            print("利用可能なモデル:")
            print(model_files)
            model_name = input("読み込むモデル名を入力してください.\n！注意！過去にモデル構造を変更している場合は読み込めませんので、config.pyを編集してください。\n: ")
            model_path = os.path.join(folder, model_name)
            checkpoint = torch.load(model_path)
            model.load_state_dict(checkpoint['model_state_dict'])
            if optimizer:
                optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                print("オプティマイザの状態も読み込みました。")
            print(f"モデルを読み込みました: {model_name}")
            return checkpoint.get('epoch', 0)
        else:
            print("利用可能なモデルが見つかりませんでした。")
            return 0
    
def main():
    # データのロード
    x_tensor, y_tensor, csv_file = load_data()
    
    # データセットとデータローダーの作成
    dataset = CustomDataset(x_tensor, y_tensor)
    dataloader = DataLoader(dataset, batch_size=config.batch_size, shuffle=True)
    
    # モデルの作成
    input_dim = x_tensor.shape[1]
    output_dim = y_tensor.shape[1]
    model = NeuralNetwork(input_dim, output_dim, config.hidden_dim, config.num_hidden_layers)
    
    # 損失関数と最適化手法の設定
    criterion = nn.MSELoss()  # Mean Squared Error
    optimizer = torch.optim.Adam(model.parameters())
        
    # モデルの読み込み
    continue_training = input("続きから学習を再開しますか？ (y): ").strip().lower() == 'y'
    start_epoch = 0
    
    if continue_training:
        start_epoch = load_model(model, None, optimizer, 'models')
    else: start_epoch =0
    try: epochs = int(input("学習するエポック数を入力してください.(デフォルト:30): ").strip())
    except ValueError: epochs = 30
    
    # モデルのトレーニング
    epoch = train_model(model, dataloader, criterion, optimizer, start_epoch=start_epoch, epochs=epochs)
    
    # モデルの保存
    model_path = save_model(model, optimizer, 'models', csv_file, epoch)
    
    # 推論の実行例
    ## NNモデルの読み込み
    #model = NeuralNetwork(input_dim, output_dim)
    model_dir = "models"
    #model_name = config.model_name #"model_20240527_record_20240519_224821.csv.pth"
    #model_path = os.path.join(model_dir, model_name)
 
   # 保存したモデルを再度ロード
    print("\n保存したモデルを再度ロードします。")
    load_model(model, model_path, None, model_dir)
    print(model)
 
    print("\n推論の実行例です。ランダムに5つのデータを取り出して予測します。")
    # dataの取り出し
    testloader = DataLoader(dataset, batch_size=1, shuffle=True)
    tmp = testloader.__iter__()
    x = torch.tensor([])
    y = torch.tensor([])
    yh = torch.tensor([])
    for _ in range(5):
        x1, y1 = next(tmp) # 1バッチ分のデータを取り出す
        yh1 = model.predict(model, x1)
        x = torch.cat([x, x1])
        y = torch.cat([y, y1])
        yh = torch.cat([yh, yh1])

    print("\n入力データ:")
    print(x)
    print("\n正解データ:")
    print(y)
    print("\n予測結果:")
    print(yh)
    print("\n差分:")
    print(y-yh)
    print("\n使用したモデル：",os.path.split(model_path)[-1])

if __name__ == "__main__":
    main()
